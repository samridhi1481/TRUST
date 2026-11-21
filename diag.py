import os, socket, ssl, logging, sys
from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv("TRUST/member2_graph/.env")
uri = os.environ["NEO4J_URI"]
user = os.environ["NEO4J_USERNAME"]
pwd = os.environ["NEO4J_PASSWORD"]

scheme, rest = uri.split("://", 1)
host = rest.split(":")[0].split("/")[0]
print("scheme:", scheme, "| host:", host)

# 1. DNS
try:
    print("DNS ->", socket.gethostbyname(host))
except Exception as e:
    print("DNS FAILED:", e); sys.exit(1)

# 2. Raw TLS handshake on 7687
try:
    ctx = ssl.create_default_context()
    with socket.create_connection((host, 7687), timeout=10) as s:
        with ctx.wrap_socket(s, server_hostname=host) as t:
            print("TLS OK:", t.version())
except Exception as e:
    print("TLS FAILED:", repr(e))

# 3. Try both schemes with driver debug logging
logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)
for sch in ("bolt+s", "neo4j+s"):
    print("\n=== trying", sch)
    try:
        d = GraphDatabase.driver(f"{sch}://{host}", auth=(user, pwd))
        d.verify_connectivity()
        print("CONNECTED with", sch)
        d.close()
        break
    except Exception as e:
        print("FAILED", sch, repr(e))