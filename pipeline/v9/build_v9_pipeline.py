"""
v9 pipeline: createACompletionGeminiPro + util:SetVariables for score pre-computation
Architecture:
  1. gateway:CustomWebHook
  2. builtin:BasicFeeder (iterator)
  3. gemini-ai:createACompletionGeminiPro (JSON response → {{3.result.*}})
  4. util:SetVariables (pre-computes score and individual indicators as integers)
  5. mistral-ai:createEmbeddings
  6. qdrant:uploadPoint (uses {{4.score}}, {{4.vl}}, etc.)
"""
import json

GEMINI_CONN_ID = 8749989
MISTRAL_CONN_ID = 8749892
QDRANT_CONN_ID = 8774749

SYSTEM_PROMPT = """You are an ESG audit specialist. Evaluate ESG claims on 5 substantiation criteria.
Return true if the criterion is MET, false if NOT MET.

Criteria:
- vague_language: true if the claim uses SPECIFIC language (NOT vague phrases like "committed to", "working towards", "aims to", "strives to", "deeply committed"). False if vague.
- quantification: true if the claim includes a specific number, percentage, or measurable metric. False if no numbers.
- baseline: true if the claim references a baseline year, starting point, or comparison value. False if no baseline.
- time_bound: true if the claim specifies a target year, deadline, or time period. False if no timeframe.
- third_party_verification: true if the claim mentions third-party verification, certification, or audit. False if self-reported only.

Return ONLY a valid JSON object with these 5 boolean fields. No explanation, no markdown."""

USER_PROMPT = "Evaluate this ESG claim: {{2.raw_text}}"

# Use payloadSimple to avoid JSON escaping issues with raw_text
# payloadSimple uses structured key-value pairs
PAYLOAD_SIMPLE = [
    {"key": "claim_id", "valueType": "string", "value": "{{2.claim_id}}"},
    {"key": "job_id", "valueType": "string", "value": "{{1.job_id}}"},
    {"key": "company_name", "valueType": "string", "value": "{{1.company_name}}"},
    {"key": "raw_text", "valueType": "string", "value": "{{2.raw_text}}"},
    {"key": "category", "valueType": "string", "value": "{{2.category}}"},
    {"key": "unit", "valueType": "string", "value": "{{2.unit}}"},
    {"key": "numeric_value", "valueType": "string", "value": "{{2.numeric_value}}"},
    {"key": "reporting_year", "valueType": "string", "value": "{{2.reporting_year}}"},
    {"key": "vague_language", "valueType": "int", "value": "{{4.vl}}"},
    {"key": "quantification", "valueType": "int", "value": "{{4.qu}}"},
    {"key": "baseline", "valueType": "int", "value": "{{4.ba}}"},
    {"key": "time_bound", "valueType": "int", "value": "{{4.tb}}"},
    {"key": "third_party_verification", "valueType": "int", "value": "{{4.tp}}"},
    {"key": "substantiation_score", "valueType": "int", "value": "{{4.score}}"},
    {"key": "status", "valueType": "string", "value": "pending_review"},
    {"key": "pipeline_version", "valueType": "string", "value": "v9"}
]

blueprint = {
    "flow": [
        {
            "id": 1,
            "module": "gateway:CustomWebHook",
            "version": 1,
            "mapper": {},
            "parameters": {"hook": 3338114, "maxResults": 1},
            "metadata": {
                "restore": {
                    "parameters": {
                        "hook": {
                            "data": {"name": "VeriGreen_ESG_Upload_Webhook", "editable": True}
                        }
                    }
                },
                "designer": {"x": 0, "y": 0}
            }
        },
        {
            "id": 2,
            "module": "builtin:BasicFeeder",
            "version": 1,
            "mapper": {"array": "{{1.claims}}"},
            "parameters": {},
            "metadata": {"designer": {"x": 300, "y": 0}}
        },
        {
            "id": 3,
            "module": "gemini-ai:createACompletionGeminiPro",
            "version": 1,
            "mapper": {
                "model": "gemini-2.5-flash",
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": USER_PROMPT, "type": "text"}]
                    }
                ],
                "system_instruction": {
                    "parts": [{"text": SYSTEM_PROMPT}]
                },
                "generationConfig": {
                    "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingBudget": 0}
                }
            },
            "parameters": {"__IMTCONN__": GEMINI_CONN_ID},
            "metadata": {"designer": {"x": 600, "y": 0}}
        },
        {
            "id": 4,
            "module": "util:SetVariables",
            "version": 1,
            "mapper": {
                "scope": "roundtrip",
                "variables": [
                    {"name": "vl", "value": "{{3.result.vague_language}}"},
                    {"name": "qu", "value": "{{3.result.quantification}}"},
                    {"name": "ba", "value": "{{3.result.baseline}}"},
                    {"name": "tb", "value": "{{3.result.time_bound}}"},
                    {"name": "tp", "value": "{{3.result.third_party_verification}}"},
                    {"name": "score", "value": "{{3.result.vague_language + 3.result.quantification + 3.result.baseline + 3.result.time_bound + 3.result.third_party_verification}}"}
                ]
            },
            "parameters": {},
            "metadata": {"designer": {"x": 900, "y": 0}}
        },
        {
            "id": 5,
            "module": "mistral-ai:createEmbeddings",
            "version": 1,
            "mapper": {
                "input": ["{{2.raw_text}}"],
                "model": "mistral-embed",
                "encoding_format": "float"
            },
            "parameters": {"__IMTCONN__": MISTRAL_CONN_ID},
            "metadata": {"designer": {"x": 1200, "y": 0}}
        },
        {
            "id": 6,
            "module": "qdrant:uploadPoint",
            "version": 1,
            "mapper": {
                "id": "{{2.id_int}}",
                "idType": "unint",
                "vector": "{{5.data[].embedding}}",
                "payloadSimple": PAYLOAD_SIMPLE,
                "payloadType": "simple",
                "collectionName": "esg_claims"
            },
            "parameters": {"__IMTCONN__": QDRANT_CONN_ID},
            "metadata": {"designer": {"x": 1500, "y": 0}}
        }
    ],
    "name": "ESG Validation Pipeline v9 (SetVariables Score)",
    "metadata": {
        "zone": "eu1.make.com",
        "instant": True,
        "version": 1,
        "designer": {"orphans": []},
        "scenario": {
            "dlq": False,
            "dataloss": False,
            "maxErrors": 3,
            "autoCommit": True,
            "roundtrips": 1,
            "sequential": False,
            "confidential": False,
            "freshVariables": False,
            "autoCommitTriggerLast": True
        }
    },
    "scheduling": {
        "type": "immediately",
        "maximum_runs_per_minute": 100
    },
    "interface": {"input": [], "output": []}
}

mcp_input = {"scenarioId": 6411040, "blueprint": blueprint}
with open("/tmp/mcp_v9_blueprint.json", "w") as f:
    json.dump(mcp_input, f, indent=2)

print("v9 blueprint saved to /tmp/mcp_v9_blueprint.json")
print(f"Modules: {[m['module'] for m in blueprint['flow']]}")
print("SetVariables computes: vl, qu, ba, tb, tp, score")
print("Qdrant payloadSimple uses structured key-value pairs (no JSON escaping issues)")
