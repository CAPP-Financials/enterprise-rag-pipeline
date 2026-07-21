"""
Lean 5-module ESG Validation Pipeline for Make.com -- v5
Architecture: Webhook -> Iterator -> Gemini Score -> Mistral Embed -> Qdrant
Cost: ~13 ops per 3-claim run (~13-20 credits per test)

All module names, connection IDs, and mapper structures confirmed from live v4 blueprint.
Key corrections vs prior attempts:
  - gemini-ai:extractStructuredData (not generateContent)
  - qdrant:uploadPoint (not qdrant2:uploadPoint)
  - Qdrant conn ID = 8774749 (not 8763715)
  - Mistral mapper key = encoding_format (not encodingFormat)
  - BasicFeeder: array goes in mapper, not parameters
  - Qdrant: payloadType=json + payloadJson string (not payload dict)
"""
import json, requests

MAKE_TOKEN = "967b02bd-c9ae-447d-a311-1170731fccde"
SCENARIO_ID = 6411040
BASE_URL = "https://eu1.make.com/api/v2"

# Connection IDs -- confirmed from live v4 blueprint
GEMINI_CONN_ID = 8749989    # gemini-ai-q9zyjp (My Gemini AI connection)
MISTRAL_CONN_ID = 8749892   # Mistral AI
QDRANT_CONN_ID = 8774749    # Qdrant -- confirmed from live blueprint module 7

SUBSTANTIATION_PROMPT = (
    "You are an ESG audit specialist. Score the following ESG claim on 5 substantiation indicators. "
    "Each indicator is scored 1 (pass) or 0 (fail).\n\n"
    "Claim: {{2.raw_text}}\n\n"
    "Indicators:\n"
    "1. vague_language: 1 if specific language (NOT vague like 'committed to', 'working towards', 'aims to'), 0 if vague.\n"
    "2. quantification: 1 if the claim includes a specific number or percentage, 0 if not.\n"
    "3. baseline: 1 if references a baseline year or comparison point, 0 if not.\n"
    "4. time_bound: 1 if specifies a target year or deadline, 0 if not.\n"
    "5. third_party_verification: 1 if mentions third-party verification or certification, 0 if not.\n\n"
    "substantiation_score = sum of all 5 indicators (0-5).\n\n"
    "Return ONLY a valid JSON object with exactly these 6 integer fields."
)

QDRANT_PAYLOAD_JSON = (
    '{"claim_id":"{{2.claim_id}}",'
    '"job_id":"{{1.job_id}}",'
    '"company_name":"{{1.company_name}}",'
    '"raw_text":"{{2.raw_text}}",'
    '"category":"{{2.category}}",'
    '"unit":"{{2.unit}}",'
    '"numeric_value":{{ifempty(2.numeric_value, "null")}},'
    '"reporting_year":"{{2.reporting_year}}",'
    '"vague_language":{{3.result.vague_language}},'
    '"quantification":{{3.result.quantification}},'
    '"baseline":{{3.result.baseline}},'
    '"time_bound":{{3.result.time_bound}},'
    '"third_party_verification":{{3.result.third_party_verification}},'
    '"substantiation_score":{{3.result.substantiation_score}},'
    '"status":"pending_review",'
    '"pipeline_version":"v5"}'
)

blueprint = {
    "name": "ESG Validation Pipeline v5 (Lean -- Claims-Direct)",
    "flow": [
        # Module 1: Webhook trigger -- receives pre-parsed claims array directly
        {
            "id": 1,
            "module": "gateway:CustomWebHook",
            "version": 1,
            "parameters": {
                "hook": 3338114,
                "maxResults": 1
            },
            "mapper": {},
            "metadata": {
                "designer": {"x": 0, "y": 0},
                "restore": {
                    "parameters": {
                        "hook": {
                            "data": {
                                "editable": True,
                                "name": "VeriGreen_ESG_Upload_Webhook"
                            }
                        }
                    }
                }
            }
        },
        # Module 2: Iterator -- loops over each claim in the claims array
        {
            "id": 2,
            "module": "builtin:BasicFeeder",
            "version": 1,
            "parameters": {},
            "mapper": {
                "array": "{{1.claims}}"
            },
            "metadata": {
                "designer": {"x": 300, "y": 0}
            }
        },
        # Module 3: Gemini extractStructuredData -- substantiation scoring
        {
            "id": 3,
            "module": "gemini-ai:extractStructuredData",
            "version": 1,
            "parameters": {
                "__IMTCONN__": GEMINI_CONN_ID
            },
            "mapper": {
                "model": "gemini-2.0-flash",
                "contents": [
                    {
                        "role": "user",
                        "parts": [
                            {
                                "type": "text",
                                "text": SUBSTANTIATION_PROMPT
                            }
                        ]
                    }
                ],
                "responseSchema": [
                    {"key": "vague_language", "label": "Vague Language (0/1)", "type": "integer"},
                    {"key": "quantification", "label": "Quantification (0/1)", "type": "integer"},
                    {"key": "baseline", "label": "Baseline (0/1)", "type": "integer"},
                    {"key": "time_bound", "label": "Time Bound (0/1)", "type": "integer"},
                    {"key": "third_party_verification", "label": "Third Party Verification (0/1)", "type": "integer"},
                    {"key": "substantiation_score", "label": "Total Score (0-5)", "type": "integer"}
                ],
                "generationConfig": {
                    "thinkingConfig": {}
                }
            },
            "metadata": {
                "designer": {"x": 600, "y": 0}
            }
        },
        # Module 4: Mistral createEmbeddings -- 1024-dim vector for the claim text
        {
            "id": 4,
            "module": "mistral-ai:createEmbeddings",
            "version": 1,
            "parameters": {
                "__IMTCONN__": MISTRAL_CONN_ID
            },
            "mapper": {
                "model": "mistral-embed",
                "input": ["{{2.raw_text}}"],
                "encoding_format": "float"
            },
            "metadata": {
                "designer": {"x": 900, "y": 0}
            }
        },
        # Module 5: Qdrant uploadPoint -- store scored + embedded claim
        {
            "id": 5,
            "module": "qdrant:uploadPoint",
            "version": 1,
            "parameters": {
                "__IMTCONN__": QDRANT_CONN_ID
            },
            "mapper": {
                "collectionName": "esg_claims",
                "id": "{{uuid()}}",
                "idType": "uuid",
                "vector": "{{4.data[].embedding}}",
                "payloadType": "json",
                "payloadJson": QDRANT_PAYLOAD_JSON
            },
            "metadata": {
                "designer": {"x": 1200, "y": 0}
            }
        }
    ],
    "metadata": {
        "instant": True,
        "version": 1,
        "scenario": {
            "roundtrips": 1,
            "maxErrors": 3,
            "autoCommit": True,
            "autoCommitTriggerLast": True,
            "sequential": False,
            "confidential": False,
            "dataloss": False,
            "dlq": False,
            "freshVariables": False
        },
        "designer": {
            "orphans": []
        },
        "zone": "eu1.make.com"
    }
}

print("Pushing lean v5 blueprint to Make.com scenario", SCENARIO_ID)
print("Blueprint module count:", len(blueprint["flow"]))

resp = requests.patch(
    f"{BASE_URL}/scenarios/{SCENARIO_ID}",
    headers={
        "Authorization": f"Token {MAKE_TOKEN}",
        "Content-Type": "application/json"
    },
    json={"blueprint": json.dumps(blueprint)},
    timeout=30
)

print(f"HTTP Status: {resp.status_code}")
if resp.status_code in (200, 201):
    print("SUCCESS: Lean v5 pipeline pushed to Make.com")
    data = resp.json()
    scenario = data.get('scenario', data.get('response', {}).get('scenario', {}))
    print(f"  Scenario ID: {scenario.get('id', SCENARIO_ID)}")
    print(f"  Is Active:   {scenario.get('isActive')}")
    print(f"  Last Edit:   {scenario.get('lastEdit')}")
    # Verify modules were accepted
    bp_str = scenario.get('blueprint', '{}')
    if isinstance(bp_str, str):
        bp_back = json.loads(bp_str)
    else:
        bp_back = bp_str
    flow = bp_back.get('flow', [])
    print(f"  Modules in blueprint: {len(flow)}")
    for m in flow:
        print(f"    [{m.get('id')}] {m.get('module')} v{m.get('version')}")
else:
    print(f"ERROR: {resp.text[:800]}")
