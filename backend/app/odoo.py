from __future__ import annotations

from decimal import Decimal
from typing import Any

import httpx

from app.config import settings
from app.domain import money


class OdooError(RuntimeError):
    pass


class OdooUnavailable(OdooError):
    pass


class OdooDefiniteError(OdooError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class OdooOutcomeUnknown(OdooError):
    pass


def _relation_id(value: Any) -> int | None:
    if isinstance(value, (list, tuple)) and value:
        return int(value[0])
    if isinstance(value, int):
        return value
    return None


class OdooJSON2Client:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        database: str | None = None,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = (base_url or settings.odoo_base_url).rstrip("/")
        self.database = database or settings.odoo_database
        self.api_key = api_key if api_key is not None else settings.odoo_api_key
        self._client = client or httpx.Client(timeout=httpx.Timeout(15.0), trust_env=False)

    def close(self) -> None:
        self._client.close()

    def _post(self, model: str, method: str, payload: dict[str, Any], *, write: bool) -> Any:
        if not self.api_key:
            raise OdooDefiniteError(401, "Odoo API key is not configured.")
        headers = {
            "Authorization": f"bearer {self.api_key}",
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": "PurchaseFlow/1.0",
            "X-Odoo-Database": self.database,
        }
        try:
            response = self._client.post(
                f"{self.base_url}/json/2/{model}/{method}",
                json=payload,
                headers=headers,
            )
        except httpx.RequestError as error:
            if write:
                raise OdooOutcomeUnknown(
                    f"Odoo {model}/{method} transport outcome is unknown ({type(error).__name__})."
                ) from None
            raise OdooUnavailable(
                f"Odoo {model}/{method} could not be queried ({type(error).__name__})."
            ) from None

        if response.status_code == 200:
            try:
                return response.json()
            except ValueError:
                if write:
                    raise OdooOutcomeUnknown(
                        f"Odoo {model}/{method} returned an unreadable success response."
                    ) from None
                raise OdooUnavailable(
                    f"Odoo {model}/{method} returned an unreadable response."
                ) from None

        if response.status_code >= 500:
            if write:
                raise OdooOutcomeUnknown(
                    f"Odoo {model}/{method} returned HTTP {response.status_code}; reconcile by intent."
                )
            raise OdooUnavailable(f"Odoo {model}/{method} returned HTTP {response.status_code}.")

        try:
            body = response.json()
            message = str(body.get("message", "Odoo rejected the request."))[:500]
        except ValueError:
            message = "Odoo rejected the request."
        raise OdooDefiniteError(response.status_code, message)

    def search_read(
        self,
        model: str,
        domain: list[list[Any]],
        fields: list[str],
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        result = self._post(
            model,
            "search_read",
            {"domain": domain, "fields": fields, "limit": limit},
            write=False,
        )
        if not isinstance(result, list) or any(not isinstance(row, dict) for row in result):
            raise OdooUnavailable(f"Odoo {model}/search_read returned an unexpected shape.")
        return result

    def read_order(self, external_intent_id: str) -> dict[str, Any] | None:
        rows = self.search_read(
            "purchase.order",
            [["purchaseflow_intent_id", "=", external_intent_id]],
            [
                "id",
                "name",
                "partner_id",
                "company_id",
                "currency_id",
                "state",
                "origin",
                "purchaseflow_intent_id",
                "order_line",
                "amount_untaxed",
                "amount_tax",
                "amount_total",
            ],
            limit=3,
        )
        if len(rows) > 1:
            return {"duplicate_rows": rows}
        if not rows:
            return None
        header = rows[0]
        line_ids = [int(value) for value in header.get("order_line", [])]
        lines: list[dict[str, Any]] = []
        if line_ids:
            lines = self.search_read(
                "purchase.order.line",
                [["id", "in", line_ids]],
                [
                    "id",
                    "order_id",
                    "product_id",
                    "product_qty",
                    "product_uom_id",
                    "price_unit",
                    "tax_ids",
                    "price_subtotal",
                    "price_tax",
                    "price_total",
                ],
                limit=10,
            )
        return {"header": header, "lines": lines}

    def create_purchase_order(self, snapshot: dict[str, Any]) -> int:
        order_lines = []
        for line in snapshot["lines"]:
            order_lines.append(
                [
                    0,
                    0,
                    {
                        "product_id": int(line["odoo_product_id"]),
                        "product_qty": float(Decimal(line["quantity"])),
                        "product_uom_id": int(line["odoo_uom_id"]),
                        "price_unit": float(Decimal(line["unit_price"])),
                        "tax_ids": [[6, 0, [int(line["odoo_tax_id"])]]],
                    },
                ]
            )
        values = {
            "partner_id": int(snapshot["odoo_partner_id"]),
            "company_id": int(snapshot["odoo_company_id"]),
            "currency_id": int(snapshot["odoo_currency_id"]),
            "origin": snapshot["erp_intent_id"],
            "purchaseflow_intent_id": snapshot["erp_intent_id"],
            "order_line": order_lines,
        }
        result = self._post("purchase.order", "create", {"vals_list": [values]}, write=True)
        if not isinstance(result, list) or len(result) != 1:
            raise OdooOutcomeUnknown("Odoo purchase.order/create returned an unexpected result.")
        return int(result[0])


def compare_order(snapshot: dict[str, Any], remote: dict[str, Any]) -> dict[str, Any]:
    differences: dict[str, Any] = {}
    if "duplicate_rows" in remote:
        return {"duplicate_order_count": len(remote["duplicate_rows"])}
    header: dict[str, Any] = remote["header"]

    expected_header: dict[str, int] = {
        "partner_id": int(snapshot["odoo_partner_id"]),
        "company_id": int(snapshot["odoo_company_id"]),
        "currency_id": int(snapshot["odoo_currency_id"]),
    }
    for field, expected_id in expected_header.items():
        actual_id = _relation_id(header.get(field))
        if actual_id != expected_id:
            differences[field] = {"expected": expected_id, "actual": actual_id}

    for field in ("state", "origin", "purchaseflow_intent_id"):
        expected_value: str = "draft" if field == "state" else str(snapshot["erp_intent_id"])
        actual_value = header.get(field)
        if actual_value != expected_value:
            differences[field] = {
                "expected": expected_value,
                "actual": actual_value,
            }

    expected_line_type = tuple[
        int,
        int,
        Decimal,
        Decimal,
        tuple[int, ...],
        Decimal,
        Decimal,
        Decimal,
    ]
    actual_line_type = tuple[
        int | None,
        int | None,
        Decimal,
        Decimal,
        tuple[int, ...],
        Decimal,
        Decimal,
        Decimal,
    ]
    expected_lines: list[expected_line_type] = [
        (
            int(source["odoo_product_id"]),
            int(source["odoo_uom_id"]),
            Decimal(source["quantity"]),
            Decimal(source["unit_price"]),
            (int(source["odoo_tax_id"]),),
            money(Decimal(source["amount_untaxed"])),
            money(Decimal(source["amount_tax"])),
            money(Decimal(source["amount_total"])),
        )
        for source in snapshot["lines"]
    ]
    actual_lines: list[actual_line_type] = []
    for source in remote["lines"]:
        actual_lines.append(
            (
                _relation_id(source.get("product_id")),
                _relation_id(source.get("product_uom_id")),
                Decimal(str(source.get("product_qty", 0))),
                Decimal(str(source.get("price_unit", 0))),
                tuple(sorted(int(value) for value in source.get("tax_ids", []))),
                money(Decimal(str(source.get("price_subtotal", 0)))),
                money(Decimal(str(source.get("price_tax", 0)))),
                money(Decimal(str(source.get("price_total", 0)))),
            )
        )

    def sort_key(
        row: tuple[Any, ...],
    ) -> tuple[int, Decimal, Decimal]:
        return (row[0] or 0, row[2], row[3])

    expected_lines.sort(key=sort_key)
    actual_lines.sort(key=sort_key)
    if len(expected_lines) != len(actual_lines):
        differences["line_count"] = {
            "expected": len(expected_lines),
            "actual": len(actual_lines),
        }
    else:
        for index, (expected_line, actual_line) in enumerate(
            zip(expected_lines, actual_lines, strict=True),
            start=1,
        ):
            if expected_line != actual_line:
                differences[f"line_{index}"] = {
                    "expected": [str(value) for value in expected_line],
                    "actual": [str(value) for value in actual_line],
                }

    for amount_field in ("amount_untaxed", "amount_tax", "amount_total"):
        expected_amount = money(Decimal(snapshot[amount_field]))
        actual_amount = money(Decimal(str(header.get(amount_field, "0"))))
        if actual_amount != expected_amount:
            differences[amount_field] = {
                "expected": str(expected_amount),
                "actual": str(actual_amount),
            }
    return differences
