import os

os.environ.setdefault("NET_RETRY_WAIT", "0")  # fleet/net.py retries must not sleep in tests
os.environ.setdefault("EGRESS_HOSTS", "")   # reconcile.check_egress probes nothing in tests; the egress test passes hosts itself
