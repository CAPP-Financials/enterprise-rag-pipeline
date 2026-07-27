"""
Golden Dataset Test Runner v9
Fires all 20 golden claims through the live Make.com pipeline in 4 batches of 5.
Webhook: https://hook.eu1.make.com/wjrgqmyidyzporevwtmbpm5x4f15thr4
"""
import json
import time
import subprocess

WEBHOOK_URL = "https://hook.eu1.make.com/wjrgqmyidyzporevwtmbpm5x4f15thr4"

with open("/home/ubuntu/golden_dataset_20.json") as f:
    claims = json.load(f)

# Build batches of 5
batches = [claims[i:i+5] for i in range(0, 20, 5)]

results = []
for batch_idx, batch in enumerate(batches):
    batch_num = batch_idx + 1
    job_id = f"golden-v9-batch{batch_num}"
    
    # Build payload
    payload = {
        "job_id": job_id,
        "company_name": "Golden Dataset Test",
        "claims": []
    }
    for claim in batch:
        payload["claims"].append({
            "claim_id": claim["claim_id"],
            "id_int": claim["id_int"],
            "raw_text": claim["raw_text"],
            "category": claim["category"],
            "unit": claim.get("unit", ""),
            "numeric_value": claim.get("numeric_value") or 0,
            "reporting_year": claim.get("reporting_year", "2024")
        })
    
    payload_json = json.dumps(payload)
    
    print(f"\n[{time.strftime('%H:%M:%S')}] Firing batch {batch_num}/4: {[c['claim_id'] for c in batch]}")
    
    result = subprocess.run(
        ["curl", "-s", "-o", "/tmp/wh_resp.txt", "-w", "%{http_code}",
         "-X", "POST", WEBHOOK_URL,
         "-H", "Content-Type: application/json",
         "-d", payload_json],
        capture_output=True, text=True, timeout=30
    )
    
    http_code = result.stdout.strip()
    print(f"  HTTP {http_code} — job_id: {job_id}")
    
    results.append({
        "batch": batch_num,
        "job_id": job_id,
        "claims": [c["claim_id"] for c in batch],
        "http_code": http_code,
        "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    })
    
    if batch_idx < 3:
        print(f"  Waiting 75s before next batch...")
        time.sleep(75)

print(f"\n[{time.strftime('%H:%M:%S')}] All 4 batches fired.")
with open("/tmp/golden_test_v9_results.json", "w") as f:
    json.dump(results, f, indent=2)
print("Results saved to /tmp/golden_test_v9_results.json")
print("\nWaiting 90s for final batch to complete...")
time.sleep(90)
print("Done. Ready to retrieve Qdrant results.")
