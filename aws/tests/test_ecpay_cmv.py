"""Known-answer test for the CheckMacValue helper copied into the M2 Lambdas.

Run: python3 aws/tests/test_ecpay_cmv.py <path to ecpay/test-vectors/checkmacvalue.json>
"""
import hashlib, json, re, sys, urllib.parse
from pathlib import Path


def load_helpers():
    # Pull the exact helper source out of a deployed Lambda so the test checks what ships.
    src = (Path(__file__).resolve().parents[1] / "lambdas" / "ecpay_return" / "index.py").read_text()
    block = re.search(r"# --- ECPay CheckMacValue ---\n(.*?)# --- end CheckMacValue ---", src, re.S).group(1)
    import hmac
    ns = {"hashlib": hashlib, "urllib": urllib, "hmac": hmac}
    exec(block, ns)
    return ns


def main(path):
    ns = load_helpers()
    all_vectors = json.load(open(path))["vectors"]
    # Vectors with their own "formula" (e.g. E-Ticket: SHA256 of Key+JSON+IV) are not the AIO algorithm.
    vectors = [v for v in all_vectors if "params" in v and not v.get("formula")]
    for v in all_vectors:
        if v not in vectors:
            print(f"SKIP  {v['name']} (formula={v.get('formula')}, not AIO)")
    ok = 0
    for v in vectors:
        got = ns["gen_cmv"](v["params"], v["hashKey"], v["hashIV"], v.get("method", "SHA256"))
        status = "PASS" if got == v["expected"] else "FAIL"
        ok += status == "PASS"
        print(f"{status}  {v['name']}" + ("" if status == "PASS" else f"\n      got {got}\n      exp {v['expected']}"))
    print(f"{ok}/{len(vectors)} passed")
    sys.exit(0 if ok == len(vectors) else 1)


if __name__ == "__main__":
    main(sys.argv[1])
