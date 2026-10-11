from __future__ import annotations

import logging
import time
from datetime import timedelta
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, sessionmaker

from app.audit import record_audit
from app.db import SessionLocal
from app.models import ERPIntent, OutboxEvent, Procurement, utcnow
from app.odoo import (
    OdooDefiniteError,
    OdooJSON2Client,
    OdooOutcomeUnknown,
    OdooUnavailable,
    compare_order,
)

logger = logging.getLogger("purchaseflow.erp")
TOPIC_CREATE_DRAFT = "erp.create_draft"


def _persist_observation(
    factory: sessionmaker[Session],
    *,
    intent_id: UUID,
    outbox_id: UUID,
    lease_generation: int,
    state: str,
    disposition: str,
    write_attempted: bool,
    event_status: str,
    procurement_status: str | None = None,
    remote: dict | None = None,
    differences: dict | None = None,
    error: str | None = None,
    retry_seconds: int = 0,
) -> bool:
    with factory() as db:
        now = utcnow()
        event = db.execute(
            select(OutboxEvent)
            .where(
                OutboxEvent.id == outbox_id,
                OutboxEvent.status == "processing",
                OutboxEvent.lease_generation == lease_generation,
            )
            .with_for_update()
        ).scalar_one_or_none()
        lease_until = event.lease_until if event is not None else None
        if lease_until is not None and lease_until.tzinfo is None:
            lease_until = lease_until.replace(tzinfo=now.tzinfo)
        if event is None or lease_until is None or lease_until <= now:
            logger.info(
                "Discarded stale ERP worker observation for outbox %s generation %s",
                outbox_id,
                lease_generation,
            )
            return False
        intent = db.execute(
            select(ERPIntent).where(ERPIntent.id == intent_id).with_for_update()
        ).scalar_one()
        procurement = db.execute(
            select(Procurement).where(Procurement.id == intent.procurement_id).with_for_update()
        ).scalar_one()
        old_status = procurement.status
        intent.state = state
        if remote and remote.get("header"):
            intent.remote_order_id = int(remote["header"]["id"])
            intent.remote_order_name = str(remote["header"]["name"])
        intent.last_error = error[:2000] if error else None
        intent.observed_at = utcnow()
        intent.last_observation = {
            "disposition": disposition,
            "observed_at": intent.observed_at.isoformat(),
            "write_attempted": write_attempted,
            "remote": remote,
            "differences": differences,
            "error": intent.last_error,
        }
        event.status = event_status
        event.lease_until = None
        event.last_error = intent.last_error
        if event_status == "pending":
            event.available_at = utcnow() + timedelta(seconds=retry_seconds)
        if procurement_status and procurement.status != procurement_status:
            procurement.status = procurement_status
            procurement.version += 1
        db.flush()
        record_audit(
            db,
            organization_id=procurement.organization_id,
            actor_user_id=None,
            action=f"erp.{disposition.lower()}",
            resource_type="procurement",
            resource_id=str(procurement.id),
            before={"status": old_status},
            after={
                "status": procurement.status,
                "intent_id": str(intent.id),
                "disposition": disposition,
                "remote_order_id": intent.remote_order_id,
            },
            metadata={"write_attempted": write_attempted, "error": intent.last_error},
        )
        db.commit()
        return True


def _complete_remote(
    factory: sessionmaker[Session],
    *,
    intent_id: UUID,
    outbox_id: UUID,
    lease_generation: int,
    remote: dict,
) -> None:
    with factory() as db:
        intent = db.execute(select(ERPIntent).where(ERPIntent.id == intent_id)).scalar_one()
        snapshot = dict(intent.expected_snapshot)
    differences = compare_order(snapshot, remote)
    if differences:
        _persist_observation(
            factory,
            intent_id=intent_id,
            outbox_id=outbox_id,
            lease_generation=lease_generation,
            state="mismatch",
            disposition="MISMATCH",
            write_attempted=True,
            event_status="done",
            procurement_status="erp_mismatch",
            remote=remote,
            differences=differences,
            error="Odoo facts do not match the approved request snapshot.",
        )
        return
    _persist_observation(
        factory,
        intent_id=intent_id,
        outbox_id=outbox_id,
        lease_generation=lease_generation,
        state="verified",
        disposition="VERIFIED",
        write_attempted=True,
        event_status="done",
        procurement_status="erp_verified",
        remote=remote,
    )


def process_one(
    factory: sessionmaker[Session] = SessionLocal,
    client: OdooJSON2Client | None = None,
    *,
    lease_seconds: int = 45,
    outbox_id: UUID | None = None,
) -> bool:
    owns_client = client is None
    client = client or OdooJSON2Client()
    try:
        with factory() as db:
            now = utcnow()
            event_query = select(OutboxEvent).where(
                OutboxEvent.topic == TOPIC_CREATE_DRAFT,
                OutboxEvent.available_at <= now,
                or_(
                    OutboxEvent.status == "pending",
                    (OutboxEvent.status == "processing") & (OutboxEvent.lease_until < now),
                ),
            )
            if outbox_id is not None:
                event_query = event_query.where(OutboxEvent.id == outbox_id)
            event = db.execute(
                event_query.order_by(OutboxEvent.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            ).scalar_one_or_none()
            if event is None:
                return False
            intent_id = UUID(event.payload_json["erp_intent_id"])
            intent = db.execute(
                select(ERPIntent).where(ERPIntent.id == intent_id).with_for_update()
            ).scalar_one()
            procurement = db.execute(
                select(Procurement).where(Procurement.id == intent.procurement_id).with_for_update()
            ).scalar_one()
            prior_state = intent.state
            prior_observation = intent.last_observation or {}
            can_create = prior_state == "pending" or (
                prior_state == "unavailable" and not prior_observation.get("write_attempted", False)
            )
            event.status = "processing"
            event.lease_until = now + timedelta(seconds=lease_seconds)
            event.attempts += 1
            intent.attempts += 1
            intent.state = "dispatching"
            event.lease_generation += 1
            lease_generation = event.lease_generation
            attempt = event.attempts
            if procurement.status in {"approved", "erp_unavailable"}:
                procurement.status = "erp_pending"
                procurement.version += 1
            snapshot = dict(intent.expected_snapshot)
            outbox_id = event.id
            db.commit()

        try:
            remote = client.read_order(snapshot["erp_intent_id"])
        except OdooUnavailable as error:
            state = "unavailable" if can_create else "unknown"
            disposition = "UNAVAILABLE" if can_create else "UNKNOWN"
            _persist_observation(
                factory,
                intent_id=intent_id,
                outbox_id=outbox_id,
                lease_generation=lease_generation,
                state=state,
                disposition=disposition,
                write_attempted=not can_create,
                event_status="pending" if can_create else "done",
                procurement_status="erp_pending" if can_create else "erp_unknown",
                error=str(error),
                retry_seconds=min(60, 2 ** min(5, attempt)),
            )
            return True

        if remote is not None:
            _complete_remote(
                factory,
                intent_id=intent_id,
                outbox_id=outbox_id,
                lease_generation=lease_generation,
                remote=remote,
            )
            return True

        if not can_create:
            _persist_observation(
                factory,
                intent_id=intent_id,
                outbox_id=outbox_id,
                lease_generation=lease_generation,
                state="unknown",
                disposition="ABSENT",
                write_attempted=True,
                event_status="done",
                procurement_status="erp_unknown",
                error="A prior create attempt may have committed; no remote order is currently visible.",
            )
            return True

        try:
            client.create_purchase_order(snapshot)
        except OdooOutcomeUnknown as error:
            _persist_observation(
                factory,
                intent_id=intent_id,
                outbox_id=outbox_id,
                state="unknown",
                disposition="UNKNOWN",
                write_attempted=True,
                event_status="done",
                procurement_status="erp_unknown",
                error=str(error),
            )
            return True
        except OdooDefiniteError as error:
            if error.status_code in {409, 422}:
                try:
                    duplicate = client.read_order(snapshot["erp_intent_id"])
                except OdooUnavailable as read_error:
                    _persist_observation(
                        factory,
                        intent_id=intent_id,
                        outbox_id=outbox_id,
                        lease_generation=lease_generation,
                        state="unknown",
                        disposition="UNKNOWN",
                        write_attempted=True,
                        event_status="done",
                        procurement_status="erp_unknown",
                        error=f"Duplicate response could not be reconciled: {read_error}",
                    )
                    return True
                if duplicate is not None:
                    _complete_remote(
                    factory,
                    intent_id=intent_id,
                    outbox_id=outbox_id,
                    lease_generation=lease_generation,
                    remote=duplicate,
                    )
                    return True
            _persist_observation(
                factory,
                intent_id=intent_id,
                outbox_id=outbox_id,
                lease_generation=lease_generation,
                state="failed",
                disposition="FAILED",
                write_attempted=True,
                event_status="dead",
                procurement_status="erp_failed",
                error=str(error),
            )
            return True

        try:
            verified_remote = client.read_order(snapshot["erp_intent_id"])
        except OdooUnavailable as error:
            _persist_observation(
                factory,
                intent_id=intent_id,
                outbox_id=outbox_id,
                lease_generation=lease_generation,
                state="unknown",
                disposition="UNKNOWN",
                write_attempted=True,
                event_status="done",
                procurement_status="erp_unknown",
                error=f"Create response received, but independent read-back failed: {error}",
            )
            return True
        if verified_remote is None:
            _persist_observation(
                factory,
                intent_id=intent_id,
                outbox_id=outbox_id,
                lease_generation=lease_generation,
                state="unknown",
                disposition="UNKNOWN",
                write_attempted=True,
                event_status="done",
                procurement_status="erp_unknown",
                error="Create response received, but the order was absent from independent read-back.",
            )
            return True
        _complete_remote(
            factory,
            intent_id=intent_id,
            outbox_id=outbox_id,
            lease_generation=lease_generation,
            remote=verified_remote,
        )
        return True
    finally:
        if owns_client:
            client.close()


def serve(poll_seconds: float = 2.0) -> None:
    client = OdooJSON2Client()
    try:
        while True:
            try:
                processed = process_one(client=client)
                if not processed:
                    time.sleep(poll_seconds)
            except Exception:
                logger.exception("PurchaseFlow worker iteration failed.")
                time.sleep(poll_seconds)
    finally:
        client.close()


def _persist_manual_absence(
    db: Session,
    *,
    intent: ERPIntent,
    procurement: Procurement,
    principal,
    previous_state: str,
    write_attempted: bool,
    error: str | None = None,
) -> None:
    old_status = procurement.status
    if previous_state in {"unknown", "dispatching"}:
        intent.state = "unknown"
        procurement.status = "erp_unknown"
    elif previous_state in {"failed", "mismatch", "verified", "blocked"}:
        intent.state = previous_state
    else:
        intent.state = "pending"
        if procurement.status == "erp_unavailable":
            procurement.status = "erp_pending"
    intent.observed_at = utcnow()
    intent.last_error = error[:2000] if error else None
    intent.last_observation = {
        "disposition": "ABSENT",
        "observed_at": intent.observed_at.isoformat(),
        "write_attempted": write_attempted,
        "manual_reconcile": True,
        "error": intent.last_error,
    }
    if old_status != procurement.status:
        procurement.version += 1
    record_audit(
        db,
        organization_id=procurement.organization_id,
        actor_user_id=principal.user_id,
        action="erp.manual_reconcile_absent",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": old_status},
        after={"status": procurement.status, "intent_state": intent.state},
        metadata={"external_intent_id": intent.external_intent_id},
    )
    db.commit()


def _persist_manual_unavailable(
    db: Session,
    *,
    intent: ERPIntent,
    procurement: Procurement,
    principal,
    previous_state: str,
    write_attempted: bool,
    error: str,
) -> None:
    old_status = procurement.status
    if previous_state not in {"unknown", "dispatching"}:
        intent.state = "unavailable"
        if procurement.status in {"approved", "erp_unavailable"}:
            procurement.status = (
                "erp_pending" if procurement.status == "approved" else procurement.status
            )
    else:
        intent.state = "unknown"
        procurement.status = "erp_unknown"
    intent.observed_at = utcnow()
    intent.last_error = error[:2000]
    intent.last_observation = {
        "disposition": "UNAVAILABLE",
        "observed_at": intent.observed_at.isoformat(),
        "write_attempted": write_attempted,
        "manual_reconcile": True,
        "error": intent.last_error,
    }
    if old_status != procurement.status:
        procurement.version += 1
    record_audit(
        db,
        organization_id=procurement.organization_id,
        actor_user_id=principal.user_id,
        action="erp.manual_reconcile_unavailable",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": old_status},
        after={"status": procurement.status, "intent_state": intent.state},
        metadata={"external_intent_id": intent.external_intent_id, "error": error[:500]},
    )
    db.commit()


def _persist_manual_remote(
    db: Session,
    *,
    intent: ERPIntent,
    procurement: Procurement,
    principal,
    remote: dict,
) -> None:
    differences = compare_order(dict(intent.expected_snapshot), remote)
    old_status = procurement.status
    header = remote.get("header")
    if header:
        intent.remote_order_id = int(header["id"])
        intent.remote_order_name = str(header["name"])
    intent.observed_at = utcnow()
    intent.last_error = None
    if differences:
        intent.state = "mismatch"
        procurement.status = "erp_mismatch"
        disposition = "MISMATCH"
    else:
        intent.state = "verified"
        procurement.status = "erp_verified"
        disposition = "VERIFIED"
    intent.last_observation = {
        "disposition": disposition,
        "observed_at": intent.observed_at.isoformat(),
        "write_attempted": True,
        "manual_reconcile": True,
        "remote": remote,
        "differences": differences,
    }
    if old_status != procurement.status:
        procurement.version += 1
    event = db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.topic == TOPIC_CREATE_DRAFT,
            OutboxEvent.aggregate_id == str(intent.id),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if event is not None:
        event.status = "done"
        event.lease_until = None
        event.last_error = None
    record_audit(
        db,
        organization_id=procurement.organization_id,
        actor_user_id=principal.user_id,
        action=f"erp.manual_reconcile_{disposition.lower()}",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": old_status},
        after={
            "status": procurement.status,
            "intent_state": intent.state,
            "remote_order_id": intent.remote_order_id,
            "remote_order_name": intent.remote_order_name,
        },
        metadata={"external_intent_id": intent.external_intent_id, "differences": differences},
    )
    db.commit()


def reconcile_manually(
    db: Session, principal, procurement_id: UUID, client: OdooJSON2Client
) -> Procurement:
    from app.domain import NotFound, PermissionDenied

    if principal.role not in {"finance", "procurement"}:
        raise PermissionDenied("Only Finance or Procurement may reconcile an ERP result.")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    intent = db.execute(
        select(ERPIntent).where(ERPIntent.procurement_id == procurement.id).with_for_update()
    ).scalar_one_or_none()
    if intent is None:
        raise NotFound("No ERP intent exists for this request.")
    intent_id = intent.id
    marker = intent.external_intent_id
    previous_state = intent.state
    prior_write_attempted = bool((intent.last_observation or {}).get("write_attempted", False))
    db.commit()

    try:
        remote = client.read_order(marker)
    except (OdooUnavailable, OdooDefiniteError) as error:
        procurement = db.execute(
            select(Procurement).where(Procurement.id == procurement_id)
        ).scalar_one()
        intent = db.execute(select(ERPIntent).where(ERPIntent.id == intent_id)).scalar_one()
        _persist_manual_unavailable(
            db,
            intent=intent,
            procurement=procurement,
            principal=principal,
            previous_state=previous_state,
            write_attempted=prior_write_attempted,
            error=str(error),
        )
        return procurement

    procurement = db.execute(
        select(Procurement).where(Procurement.id == procurement_id).with_for_update()
    ).scalar_one()
    intent = db.execute(
        select(ERPIntent).where(ERPIntent.id == intent_id).with_for_update()
    ).scalar_one()
    if remote is None:
        _persist_manual_absence(
            db,
            intent=intent,
            procurement=procurement,
            principal=principal,
            previous_state=previous_state,
            write_attempted=prior_write_attempted,
        )
    else:
        _persist_manual_remote(
            db,
            intent=intent,
            procurement=procurement,
            principal=principal,
            remote=remote,
        )
    return procurement


def authorize_manual_retry(
    db: Session, principal, procurement_id: UUID, client: OdooJSON2Client
) -> Procurement:
    from app.domain import Conflict, NotFound, PermissionDenied

    if principal.role != "procurement":
        raise PermissionDenied("Only Procurement may authorize a controlled ERP retry.")
    procurement = db.execute(
        select(Procurement)
        .where(
            Procurement.id == procurement_id,
            Procurement.organization_id == principal.organization_id,
        )
        .with_for_update()
    ).scalar_one_or_none()
    if procurement is None:
        raise NotFound("Procurement request was not found.")
    intent = db.execute(
        select(ERPIntent).where(ERPIntent.procurement_id == procurement.id).with_for_update()
    ).scalar_one_or_none()
    if intent is None:
        raise NotFound("No ERP intent exists for this request.")
    if intent.state not in {"unknown", "unavailable", "failed"}:
        raise Conflict("Only an UNKNOWN, UNAVAILABLE, or FAILED intent can be manually retried.")
    intent_id = intent.id
    marker = intent.external_intent_id
    expected_state = intent.state
    db.commit()

    try:
        remote = client.read_order(marker)
    except (OdooUnavailable, OdooDefiniteError) as error:
        procurement = db.execute(
            select(Procurement).where(Procurement.id == procurement_id)
        ).scalar_one()
        intent = db.execute(select(ERPIntent).where(ERPIntent.id == intent_id)).scalar_one()
        _persist_manual_unavailable(
            db,
            intent=intent,
            procurement=procurement,
            principal=principal,
            previous_state=expected_state,
            write_attempted=True,
            error=str(error),
        )
        return procurement

    procurement = db.execute(
        select(Procurement).where(Procurement.id == procurement_id).with_for_update()
    ).scalar_one()
    intent = db.execute(
        select(ERPIntent).where(ERPIntent.id == intent_id).with_for_update()
    ).scalar_one()
    if intent.state != expected_state:
        raise Conflict("ERP intent changed while the remote observation was in progress.")
    if remote is not None:
        _persist_manual_remote(
            db,
            intent=intent,
            procurement=procurement,
            principal=principal,
            remote=remote,
        )
        return procurement

    event = db.execute(
        select(OutboxEvent)
        .where(
            OutboxEvent.topic == TOPIC_CREATE_DRAFT,
            OutboxEvent.aggregate_id == str(intent.id),
        )
        .with_for_update()
    ).scalar_one_or_none()
    if event is None:
        raise Conflict("The original transactional outbox event is missing.")
    event.status = "pending"
    event.available_at = utcnow()
    event.lease_until = None
    event.last_error = None
    intent.state = "pending"
    intent.last_error = None
    intent.observed_at = utcnow()
    intent.last_observation = {
        "disposition": "ABSENT",
        "observed_at": intent.observed_at.isoformat(),
        "write_attempted": False,
        "manual_retry_authorized": True,
    }
    old_status = procurement.status
    procurement.status = "erp_pending"
    procurement.version += 1
    record_audit(
        db,
        organization_id=procurement.organization_id,
        actor_user_id=principal.user_id,
        action="erp.manual_retry_authorized",
        resource_type="procurement",
        resource_id=str(procurement.id),
        before={"status": old_status, "intent_state": expected_state},
        after={"status": procurement.status, "intent_state": intent.state},
        metadata={
            "external_intent_id": intent.external_intent_id,
            "remote_absence_confirmed": True,
        },
    )
    db.commit()
    return procurement
