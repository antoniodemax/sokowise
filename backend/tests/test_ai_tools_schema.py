"""The tool allowlist is closed, strict and never takes a tenant (PRD AI-2)."""

import json

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.tools import TOOLS, tool_definitions
from app.core.config import Settings

EXPECTED = {
    "get_business_summary",
    "get_sales_summary",
    "get_product_performance",
    "get_slow_products",
    "get_inventory_status",
    "get_debtors",
    "get_expense_summary",
    "search_customers",
}


def test_only_the_allowlisted_read_only_tools_exist() -> None:
    assert set(TOOLS) == EXPECTED
    forbidden = {"execute_sql", "query_database", "search_database", "run_report", "run_sql"}
    assert not forbidden & set(TOOLS)


def test_no_tool_accepts_a_business_id_or_free_form_filters() -> None:
    for definition in tool_definitions():
        properties = definition["input_schema"]["properties"]
        assert "business_id" not in properties, definition["name"]
        assert not {"sql", "query_expression", "table", "columns", "where"} & set(properties)


def test_tool_schemas_are_strict() -> None:
    for definition in tool_definitions():
        schema = definition["input_schema"]
        assert definition["strict"] is True
        assert schema["additionalProperties"] is False
        assert sorted(schema["properties"]) == schema["required"], definition["name"]
        json.dumps(schema)  # serialisable as sent to the provider


def test_tool_inputs_reject_unknown_fields_and_oversized_limits() -> None:
    from pydantic import ValidationError

    for name, tool in TOOLS.items():
        base = {"period": "today", "date_from": None, "date_to": None}
        try:
            tool.input_model.model_validate(
                {**base, "business_id": "x"}
                if "period" in tool.input_schema()["properties"]
                else {"business_id": "x"}
            )
        except ValidationError as exc:
            assert any(e["type"] == "extra_forbidden" for e in exc.errors()), name
        else:  # pragma: no cover
            raise AssertionError(f"{name} accepted business_id")
    for name in (
        "get_debtors",
        "get_inventory_status",
        "get_product_performance",
        "search_customers",
    ):
        try:
            payload: dict[str, object] = {"limit": 10_000}
            if name == "get_product_performance":
                payload.update(
                    {"period": "today", "date_from": None, "date_to": None, "sort": "revenue"}
                )
            if name == "search_customers":
                payload["query"] = "a"
            TOOLS[name].input_model.model_validate(payload)
        except ValidationError as exc:
            assert any(e["type"] == "less_than_equal" for e in exc.errors()), name
        else:  # pragma: no cover
            raise AssertionError(f"{name} accepted an oversized limit")


def test_system_prompt_states_the_accounting_rules_and_has_no_secrets(monkeypatch: object) -> None:
    text = SYSTEM_PROMPT.lower()
    for phrase in (
        "credit sales are not cash collected",
        "repayments are not revenue",
        "net profit",
        "understated",
        "read-only",
        "ksh",
    ):
        assert phrase in text, phrase
    assert "sk-ant" not in text and "api key" not in text


def test_ai_settings_are_operator_configuration_with_the_phase_0_defaults() -> None:
    settings = Settings()
    assert settings.ai_daily_message_limit == 10
    assert settings.ai_monthly_message_limit == 100
    assert settings.anthropic_api_key is None
    assert settings.ai_max_tool_rounds == 6
