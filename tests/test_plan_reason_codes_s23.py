"""S23: every plan-level "why not" carries reason_code and reason_args next to the English reason."""
from api import plan


def test_every_code_has_english_and_the_why_dict():
    for code, template in plan.PLAN_REASON.items():
        args = {"title": "Matilda", "edition": "hardcover", "shops": ["emag", "amazon_de"]}
        used = {k: v for k, v in args.items() if "{" + k + "}" in template}
        out = plan._why(code, **used)
        assert out["reason_code"] == code and out["reason_args"] == used
        assert "{" not in out["reason"]


def test_english_lines_are_unchanged():
    assert plan._why("no_single_shop_lists_all")["reason"] == "no single shop lists every book"
    assert plan._why("chosen_shop_unusable", shops=["emag", "amazon_de"])["reason"] == "a chosen shop cannot be used: emag, amazon_de"
    missing = [{"title": "Simon vs. the Homo Sapiens Agenda", "pin": None}]
    assert plan._missing_reason(missing, chosen=True) == {
        "reason": "no shop chosen lists Simon vs. the Homo Sapiens Agenda",
        "reason_code": "no_chosen_shop_lists",
        "reason_args": {"title": "Simon vs. the Homo Sapiens Agenda"},
    }
    pinned = [{"title": "Matilda", "pin": "hardcover"}]
    assert plan._missing_reason(pinned)["reason"] == "no shop prints Matilda as hardcover"
