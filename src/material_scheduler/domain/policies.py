from material_scheduler.domain.models import Material, ReviewResult, Rule


def review(material: Material | None, rules: list[Rule]) -> ReviewResult:
    if material is None:
        return ReviewResult(status="missing", missing=["material"])
    missing = [key for key in ("title", "rights") if getattr(material, key) is None]
    if not material.title and "title" not in missing:
        missing.append("title")
    risks = []
    if material.rights is False:
        risks.append({"rule_id": "RIGHTS", "reason": "缺少素材使用权"})
    risks.extend(
        {"rule_id": rule.rule_id, "reason": rule.reason}
        for rule in rules
        if rule.blocked_tag in material.tags
    )
    return ReviewResult(
        status="blocked" if risks else "missing" if missing else "passed",
        missing=missing,
        risks=risks,
    )
