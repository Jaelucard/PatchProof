"""Fixed PatchProof contract, deterministic evidence and bounded dataset imports.

Test identities deliberately exclude prompts and model configuration. This does
not change Eval Lab's generic case comparison contract.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import unicodedata
from collections import defaultdict
from typing import Any

from .canonical import canonical_json_bytes

CONTRACT_VERSION = "support-intent-v1"
EVALUATOR_VERSION = "strict-six-checks-v1"
FIELDS = ("order_id", "issue_type", "requested_action", "needs_review")
CHECKS = ("json", "schema", *FIELDS)
ISSUES = {"delivery_problem", "damaged_item", "wrong_item", "billing_problem", "other"}
ACTIONS = {"status_update", "cancel_order", "refund", "replacement", "other"}
PARTITIONS = ("development", "regression", "final")
MAX_IMPORT_BYTES = 2_000_000
MAX_CASES = 500
MAX_TEXT_CHARS = 12_000
MAX_RAW_CHARS = 30_000
STARTER_PROMPT = """Extract the order ID, issue type and requested action from this English support ticket.
Return only JSON with order_id, issue_type, requested_action and needs_review.
Use delivery_problem, damaged_item, wrong_item, billing_problem or other for issue_type.
Use status_update, cancel_order, refund, replacement or other for requested_action.
Keep order IDs as strings. Use null when a value is unavailable and set needs_review when clarification is needed.
Extract the customer's request; do not make company policy or approval decisions."""


class ValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    obj: dict = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"duplicate JSON key {key!r}")
        obj[key] = value
    return obj


def _finite_float(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("JSON number exceeds the finite numeric range")
    return number


def strict_json(raw: str) -> Any:
    parsed = json.loads(
        raw,
        object_pairs_hook=_pairs,
        parse_float=_finite_float,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"nonstandard JSON constant {value}")
        ),
    )

    def unicode_check(value):
        if type(value) is str:
            value.encode("utf-8")  # Reject unpaired surrogates before persistence.
        elif type(value) is list:
            for member in value:
                unicode_check(member)
        elif type(value) is dict:
            for key, member in value.items():
                unicode_check(key)
                unicode_check(member)

    unicode_check(parsed)
    return parsed


def _schema_errors(value: Any) -> list[str]:
    if type(value) is not dict:
        return ["Output must be a JSON object."]
    errors = []
    if set(value) != set(FIELDS):
        missing = sorted(set(FIELDS) - set(value))
        extra = sorted(set(value) - set(FIELDS))
        errors.append(f"Exactly four fields required; missing={missing}, extra={extra}.")
    for field in FIELDS:
        if field not in value:
            continue
        cell = value[field]
        if field == "needs_review":
            valid = type(cell) is bool
        elif field == "order_id":
            valid = cell is None or (type(cell) is str and 0 < len(cell) <= 200)
        else:
            valid = cell is None or (
                type(cell) is str and cell in (ISSUES if field == "issue_type" else ACTIONS)
            )
        if not valid:
            errors.append(f"{field}: invalid value or JSON type {cell!r}.")
    return errors


def evaluate(raw: str, expected: dict) -> dict:
    checks = dict.fromkeys(CHECKS, False)
    reasons: dict[str, str] = {}
    parsed = None
    try:
        if type(raw) is not str:
            raise ValueError("Response must be text.")
        raw.encode("utf-8")
        if len(raw) > MAX_RAW_CHARS:
            raise ValueError(f"Response exceeds {MAX_RAW_CHARS} characters.")
        parsed = strict_json(raw)
        checks["json"] = True
    except (ValueError, TypeError, RecursionError) as exc:
        reasons["json"] = f"Invalid strict JSON: {str(exc)[:300]}"
    if checks["json"]:
        schema_errors = _schema_errors(parsed)
        checks["schema"] = not schema_errors
        if schema_errors:
            reasons["schema"] = " ".join(schema_errors)[:1200]
    else:
        reasons["schema"] = "Cannot validate schema because strict JSON parsing failed."
    for field in FIELDS:
        if type(parsed) is not dict or field not in parsed:
            reasons[field] = f"{field} is missing or unavailable."
            continue
        checks[field] = (
            type(parsed[field]) is type(expected[field]) and parsed[field] == expected[field]
        )
        if not checks[field]:
            reasons[field] = (
                f"Expected {json.dumps(expected[field])}; received {json.dumps(parsed[field])}."
            )
    safe_raw = raw.encode("utf-8", "backslashreplace").decode("utf-8") if type(raw) is str else raw
    return {
        "raw": safe_raw,
        "parsed": parsed,
        "checks": checks,
        "reasons": reasons,
        "passed": all(checks.values()),
    }


def compare(baseline: dict, candidate: dict) -> dict:
    fixed = [key for key in CHECKS if not baseline["checks"][key] and candidate["checks"][key]]
    regressed = [key for key in CHECKS if baseline["checks"][key] and not candidate["checks"][key]]
    status = (
        "regressed"
        if regressed
        else ("fixed" if fixed else ("unchanged" if candidate["passed"] else "still_failing"))
    )
    return {"fixed": fixed, "regressed": regressed, "status": status}


def _normal(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def _split(cases: list[dict]) -> dict[str, list[str]]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for case in cases:
        groups[case.get("scenario_family") or ("case:" + case["id"])].append(case)
    n = len(cases)
    targets = {"development": n - 2 * (n // 4), "regression": n // 4, "final": n // 4}
    manifest: dict[str, list[str]] = {part: [] for part in PARTITIONS}
    for family, members in sorted(
        groups.items(), key=lambda item: (-len(item[1]), digest(item[0]))
    ):
        part = max(PARTITIONS, key=lambda key: targets[key] - len(manifest[key]))
        for case in sorted(members, key=lambda c: c["id"]):
            case["partition"] = part
            manifest[part].append(case["id"])
    return {part: sorted(ids) for part, ids in manifest.items()}


def build_dataset(
    name: str,
    cases: list,
    *,
    reviewed: bool = False,
    source: str = "import",
    trusted_partitions: bool = False,
    review_status: str | None = None,
) -> dict:
    errors: list[str] = []
    if type(name) is not str or not name.strip() or len(name) > 150:
        errors.append("Dataset name must contain 1–150 characters.")
    if type(cases) is not list or not 1 <= len(cases) <= MAX_CASES:
        raise ValidationError(errors + [f"cases must be a list of 1–{MAX_CASES} examples."])
    clean: list[dict] = []
    ids: set[str] = set()
    texts: dict[str, tuple[str, dict]] = {}
    for index, case in enumerate(cases, 1):
        prefix = f"Case/row {index}"
        if type(case) is not dict:
            errors.append(f"{prefix}: expected an object.")
            continue
        case_id, text, expected = case.get("id"), case.get("text"), case.get("expected")
        before = len(errors)
        if "label_status" in case and type(case["label_status"]) is not str:
            errors.append(f"{prefix}: label_status must be a string when provided.")
        if (
            case.get("label_status") in ("unresolved", "disputed")
            or case.get("unresolved") is True
            or case.get("label_dispute")
        ):
            errors.append(
                f"{prefix}: unresolved/disputed labels must be resolved before importing into scored experiments."
            )
        if type(case_id) is not str or not case_id.strip() or len(case_id) > 100:
            errors.append(f"{prefix}: id must be a nonempty string of at most 100 characters.")
        elif case_id in ids:
            errors.append(f"{prefix} ({case_id}): duplicate ID.")
        else:
            ids.add(case_id)
        if type(text) is not str or not text.strip() or len(text) > MAX_TEXT_CHARS:
            errors.append(f"{prefix}: text must contain 1–{MAX_TEXT_CHARS} characters.")
        else:
            normalized = _normal(text)
            if normalized in texts:
                previous_id, previous_expected = texts[normalized]
                conflict = " Conflicting labels." if previous_expected != expected else ""
                errors.append(f"{prefix}: normalized duplicate input of {previous_id}.{conflict}")
            else:
                texts[normalized] = (str(case_id), expected)
        for message in _schema_errors(expected):
            errors.append(f"{prefix}: expected.{message}")
        family = case.get("scenario_family")
        if family is not None and (
            type(family) is not str or not family.strip() or len(family) > 150
        ):
            errors.append(
                f"{prefix}: scenario_family must be a nonempty string up to 150 characters."
            )
        note = case.get("annotation_note")
        if note is not None and (type(note) is not str or len(note) > 2000):
            errors.append(f"{prefix}: annotation_note must be text up to 2000 characters.")
        scripts = case.get("fixture_outputs")
        if scripts is not None:
            if (
                type(scripts) is not dict
                or set(scripts) != {"baseline", "candidate_1", "candidate_2"}
                or any(
                    type(value) is not str or len(value) > MAX_RAW_CHARS
                    for value in scripts.values()
                )
            ):
                errors.append(
                    f"{prefix}: fixture_outputs requires baseline, candidate_1 and candidate_2 response strings (maximum {MAX_RAW_CHARS} characters each)."
                )
        if trusted_partitions and case.get("partition") not in PARTITIONS:
            errors.append(
                f"{prefix}: trusted demo partition must be development, regression or final."
            )
        if len(errors) != before:
            continue
        item = {"id": case_id, "text": text, "expected": expected.copy()}
        for key in ("scenario_family", "annotation_note", "fixture_outputs"):
            if case.get(key) is not None:
                item[key] = case[key].copy() if type(case[key]) is dict else case[key]
        item["case_hash"] = digest(
            {
                "id": case_id,
                "text": text,
                "expected": expected,
                "contract": CONTRACT_VERSION,
                "evaluator": EVALUATOR_VERSION,
            }
        )
        if trusted_partitions:
            item["partition"] = case["partition"]
        clean.append(item)
    if errors:
        raise ValidationError(errors[:100])
    if trusted_partitions:
        manifest = {
            part: sorted(c["id"] for c in clean if c["partition"] == part) for part in PARTITIONS
        }
        families: dict[str, set] = defaultdict(set)
        for case in clean:
            if case.get("scenario_family"):
                families[case["scenario_family"]].add(case["partition"])
        if any(len(parts) > 1 for parts in families.values()):
            raise ValidationError(["Known scenario families must stay within one partition."])
    else:
        manifest = _split(clean)
    eligible = (
        len(clean) >= 40 and len(manifest["regression"]) >= 10 and len(manifest["final"]) >= 10
    )
    status = (
        (review_status or "draft")
        if source == "demo"
        else ("user_attested" if reviewed else "draft")
    )
    if status not in {"draft", "independently_agent_checked", "user_attested"}:
        raise ValidationError(["Unknown review status."])
    warnings = ["Imports are checked for exact normalized duplicates, not semantic duplicates."]
    if not eligible:
        warnings.append(
            "Full experiments require at least 40 distinct cases and at least 10 regression and 10 final cases after grouping scenario families. This operational floor is not a statistical reliability guarantee. Load the supplied demo to inspect a full workflow."
        )
    if status != "user_attested":
        warnings.append("Expected answers await human review.")
    content = {
        "contract_version": CONTRACT_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "cases": sorted(clean, key=lambda case: case["id"]),
        "manifest": manifest,
    }
    return {
        "name": name,
        "cases": clean,
        "version_hash": digest(content),
        "manifest": manifest,
        "manifest_hash": digest(manifest),
        "contract_version": CONTRACT_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "review_status": status,
        "human_review_pending": status != "user_attested",
        "full_experiment_eligible": eligible,
        "source": source,
        "warnings": warnings,
    }


def parse_import(content: str, format: str, reviewed: bool = False) -> dict:
    try:
        valid_size = type(content) is str and len(content.encode("utf-8")) <= MAX_IMPORT_BYTES
    except UnicodeError:
        valid_size = False
    if not valid_size:
        raise ValidationError([f"Import must be UTF-8 text of at most {MAX_IMPORT_BYTES} bytes."])
    if type(reviewed) is not bool:
        raise ValidationError(["Reviewed attestation must be true or false."])
    if format == "json":
        try:
            obj = strict_json(content)
        except (ValueError, RecursionError) as exc:
            raise ValidationError([f"Invalid JSON import: {str(exc)[:300]}"]) from exc
        if type(obj) is not dict:
            raise ValidationError(["JSON import must be an object with name and cases."])
        return build_dataset(obj.get("name"), obj.get("cases"), reviewed=reviewed)
    if format != "csv":
        raise ValidationError(["Format must be json or csv."])
    try:
        reader = csv.DictReader(io.StringIO(content, newline=""), strict=True)
        columns = ["id", "text", *FIELDS]
        if (
            reader.fieldnames is None
            or len(reader.fieldnames) != len(columns)
            or set(reader.fieldnames) != set(columns)
        ):
            raise ValidationError(
                [
                    "CSV columns must be id,text,order_id,issue_type,requested_action,needs_review (each once)."
                ]
            )
        cases = []
        for index, row in enumerate(reader, 2):
            if index > MAX_CASES + 1:
                raise ValidationError([f"CSV exceeds {MAX_CASES} cases."])
            if None in row or any(value is None for value in row.values()):
                raise ValidationError([f"CSV row {index}: wrong number of cells."])
            if row["needs_review"] not in {"true", "false"}:
                raise ValidationError(
                    [f"CSV row {index}: needs_review must be exactly true or false."]
                )
            expected = {key: (row[key] if row[key] != "" else None) for key in FIELDS[:3]}
            expected["needs_review"] = row["needs_review"] == "true"
            cases.append({"id": row["id"], "text": row["text"], "expected": expected})
    except csv.Error as exc:
        raise ValidationError([f"Invalid CSV: {str(exc)[:300]}"]) from exc
    return build_dataset("Imported CSV examples", cases, reviewed=reviewed)
