"""LLM-as-judge: did the agent's answer contain each expected finding from cases.yaml?"""

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

load_dotenv()

JUDGE_MODEL = "gpt-4.1"  # ideally stronger than the agent's model

JUDGE_PROMPT = """You are grading a data incident investigation report.

For EACH expected finding, decide if the report states it (same meaning counts, exact wording does not matter).
Be strict:
- A finding counts only if the report states it clearly. A vague hint does not count.
- If the report contradicts the finding, it is not found.
Also list any claims in the report that are presented as evidence but are wrong or unsupported.

Expected findings:
{findings}

Report:
{answer}"""


class FindingGrade(BaseModel):
    finding: str
    found: bool
    reason: str = Field(description="One sentence quoting or pointing to the part of the report")


class JudgeResult(BaseModel):
    grades: list[FindingGrade]
    unsupported_claims: list[str] = Field(description="Wrong or unsupported evidence claims, empty if none")


judge_model = ChatOpenAI(model=JUDGE_MODEL, temperature=0).with_structured_output(JudgeResult)


def judge(answer: str, expected_findings: list[str]) -> dict:
    findings = "\n".join(f"- {f}" for f in expected_findings)
    result: JudgeResult = judge_model.invoke(JUDGE_PROMPT.format(findings=findings, answer=answer))
    found = [g for g in result.grades if g.found]
    return {
        "findings_score": round(len(found) / len(expected_findings), 2),
        "missing_findings": "; ".join(g.finding for g in result.grades if not g.found),
        "unsupported_claims": "; ".join(result.unsupported_claims),
        "judge_reasons": " | ".join(f"{'OK' if g.found else 'MISS'}: {g.reason}" for g in result.grades),
    }