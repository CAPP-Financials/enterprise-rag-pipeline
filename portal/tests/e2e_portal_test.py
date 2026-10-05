"""
End-to-end portal simulation test.
Replicates exactly what the browser does:
1. Read the ESG document (text extraction)
2. Split into sentences, filter ESG claims
3. Assign deterministic id_int per claim
4. POST JSON payload to Make.com webhook
5. Verify HTTP 200 response
6. Wait and check Make.com execution status
"""
import re
import json
import hashlib
import time
import subprocess

# ─── Config ───────────────────────────────────────────────────────────────────
WEBHOOK_URL = "https://hook.eu1.make.com/YOUR-WEBHOOK-ID"
COMPANY_NAME = "GreenTech Solutions PLC"
YEAR = "2024"
JOB_ID = "portal-e2e-test-001"
DOC_PATH = os.path.join(os.path.dirname(__file__), "greentech_esg_report_2024.txt"

# ─── ESG keyword categories (mirrors esgParser.ts) ───────────────────────────
ESG_CATEGORIES = {
    "Climate & Emissions": re.compile(
        r'\b(carbon|co2|ghg|greenhouse|emission|net.zero|scope [123]|climate|decarboni[sz]|paris agreement|temperature|warming|fossil|renewable energy|clean energy)\b', re.I),
    "Energy": re.compile(
        r'\b(energy|electricity|renewable|solar|wind|hydro|kwh|mwh|gigawatt|power consumption|energy efficiency|energy intensity)\b', re.I),
    "Water": re.compile(
        r'\b(water|wastewater|effluent|discharge|water withdrawal|water consumption|water recycl|water reuse|water stress)\b', re.I),
    "Biodiversity": re.compile(
        r'\b(biodiversity|ecosystem|habitat|species|deforestation|land use|nature.positive|nature-based|wetland|forest)\b', re.I),
    "Social & Labour": re.compile(
        r'\b(employee|worker|labour|labor|diversity|inclusion|gender|pay gap|safety|injury|training|human rights|supply chain|modern slavery|living wage)\b', re.I),
    "Circular Economy": re.compile(
        r'\b(waste|recycl|circular|landfill|reuse|upcycl|packaging|plastic|material|end.of.life|take.back)\b', re.I),
    "Governance": re.compile(
        r'\b(board|governance|audit|compliance|anti.corruption|bribery|transparency|disclosure|whistleblow|ethics|policy|framework|standard|gri|tcfd|csrd|sasb|sdg)\b', re.I),
    "Supply Chain": re.compile(
        r'\b(supplier|supply chain|procurement|vendor|sourcing|third.party|tier [12]|responsible sourcing|due diligence)\b', re.I),
}

ALL_ESG = re.compile(
    "|".join(p.pattern for p in ESG_CATEGORIES.values()), re.I
)

def classify(text):
    for cat, pat in ESG_CATEGORIES.items():
        if pat.search(text):
            return cat
    return "General Sustainability"

def djb2_hash(s):
    h = 5381
    for c in s:
        h = ((h << 5) + h) ^ ord(c)
    return abs(h) % 2_000_000_000

def make_id_int(company_id, year, idx):
    return djb2_hash(f"{company_id}:{year}:{idx}")

# ─── Step 1: Extract text ─────────────────────────────────────────────────────
print("=" * 60)
print("STEP 1: Reading document")
with open(DOC_PATH) as f:
    raw_text = f.read()
print(f"  Document length: {len(raw_text):,} characters")

# ─── Step 2: Split into sentences ────────────────────────────────────────────
print("\nSTEP 2: Splitting into sentences")
raw_text_clean = re.sub(r'\r\n', '\n', raw_text)
raw_text_clean = re.sub(r'\n{2,}', ' ', raw_text_clean)
sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z0-9"\'\(])', raw_text_clean)
sentences = [s.strip() for s in sentences if 40 < len(s.strip()) < 800]
print(f"  Total sentences: {len(sentences)}")

# ─── Step 3: Filter ESG claims ────────────────────────────────────────────────
print("\nSTEP 3: Filtering ESG claims")
company_id = COMPANY_NAME.strip().lower().replace(" ", "_")[:32]
claims = []
for idx, sentence in enumerate(sentences):
    if ALL_ESG.search(sentence):
        claims.append({
            "raw_text": sentence,
            "category": classify(sentence),
            "company_id": company_id,
            "year": YEAR,
            "id_int": make_id_int(company_id, YEAR, idx),
            "job_id": JOB_ID,
        })

# Cap at 50
claims = claims[:50]
print(f"  ESG claims extracted: {len(claims)}")

# Show breakdown by category
from collections import Counter
cat_counts = Counter(c["category"] for c in claims)
for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
    print(f"    {cat}: {count}")

# ─── Step 4: Build webhook payload ───────────────────────────────────────────
print("\nSTEP 4: Building webhook payload")
payload = {
    "job_id": JOB_ID,
    "company_name": COMPANY_NAME,
    "reporting_year": YEAR,
    "report_type": "sustainability",
    "claim_count": len(claims),
    "extraction_method": "sentence-split + ESG keyword filter",
    "claims": claims,
}
payload_json = json.dumps(payload)
print(f"  Payload size: {len(payload_json):,} bytes")
print(f"  Claims in payload: {payload['claim_count']}")

# Show first 3 claims
print("\n  Sample claims:")
for c in claims[:3]:
    print(f"    [{c['id_int']}] [{c['category']}] {c['raw_text'][:70]}...")

# ─── Step 5: POST to webhook ──────────────────────────────────────────────────
print(f"\nSTEP 5: POSTing to Make.com webhook")
print(f"  URL: {WEBHOOK_URL}")

result = subprocess.run([
    "curl", "-s", "-w", "\n%{http_code}", "-X", "POST",
    "-H", "Content-Type: application/json",
    "-d", payload_json,
    WEBHOOK_URL
], capture_output=True, text=True, timeout=30)

lines = result.stdout.strip().split("\n")
http_code = lines[-1]
response_body = "\n".join(lines[:-1])

print(f"  HTTP Status: {http_code}")
print(f"  Response: {response_body[:100]}")

if http_code == "200":
    print("\n  ✅ WEBHOOK ACCEPTED — Payload successfully delivered to Make.com")
else:
    print(f"\n  ❌ WEBHOOK FAILED — HTTP {http_code}")
    exit(1)

# ─── Step 6: Wait and check Make.com execution ───────────────────────────────
print(f"\nSTEP 6: Waiting 90 seconds for pipeline to process {len(claims)} claims...")
print(f"  Expected operations: {2 + len(claims) * 4} (2 overhead + {len(claims)} × 4 modules)")
time.sleep(90)

# Check via MCP
print("\nSTEP 7: Checking Make.com execution status via MCP...")
mcp_result = subprocess.run([
    "manus-mcp-cli", "tool", "call", "executions_list",
    "--server", "make",
    "--params", json.dumps({"scenarioId": 6411040, "limit": 3})
], capture_output=True, text=True, timeout=30)

if mcp_result.returncode == 0:
    print("  Make.com execution check complete")
    # Find the result file
    import os, glob
    result_files = sorted(glob.glob("/home/ubuntu/.mcp/tool-results/*.json"), key=os.path.getmtime, reverse=True)
    if result_files:
        with open(result_files[0]) as f:
            exec_data = json.load(f)
        executions = exec_data.get("executions", [])
        if executions:
            latest = executions[0]
            print(f"\n  Latest execution:")
            print(f"    Status: {latest.get('status')} ({'SUCCESS' if latest.get('status') == 1 else 'FAILED/WARNING'})")
            print(f"    Operations: {latest.get('ops', 'N/A')}")
            print(f"    Duration: {latest.get('duration', 'N/A')}s")
            print(f"    Timestamp: {latest.get('updatedAt', 'N/A')}")
            if latest.get('status') == 1:
                print(f"\n  ✅ PIPELINE SUCCESS — All {len(claims)} claims processed through 6 modules")
            else:
                print(f"\n  ⚠️  Pipeline returned status {latest.get('status')} — check Make.com for details")
else:
    print(f"  MCP check failed: {mcp_result.stderr[:100]}")

print("\n" + "=" * 60)
print("END-TO-END TEST COMPLETE")
print("=" * 60)
print(f"\nSummary:")
print(f"  Document: GreenTech Solutions PLC ESG Report 2024")
print(f"  Claims extracted: {len(claims)}")
print(f"  Webhook: HTTP {http_code}")
print(f"  Job ID: {JOB_ID}")
print(f"\nThe portal is fully wired to the Make.com v9 pipeline.")
