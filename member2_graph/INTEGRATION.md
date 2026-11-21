

\# TRUSTRAIL AI — Member 2 Graph Intelligence Integration



\## 1. Overview



This module provides read-only Neo4j graph intelligence operations for TRUSTRAIL AI.



It supports:

\- Entity lookup

\- Neighbour exploration

\- Subgraph retrieval

\- Attack path exploration

\- Blast radius analysis

\- Entity evidence retrieval

\- Incident evidence retrieval

\- Hypothetical containment simulation



\## 2. Import



```python

from member2\_graph.src.graph\_service import GraphService

```



Create and close the service:



```python

graph = GraphService()



try:

&#x20;   result = graph.get\_entity("HOST-001")

finally:

&#x20;   graph.close()

```



When passing an existing connection, the caller remains responsible for closing it.



\## 3. Available methods



| Method | Parameters | Purpose |

|---|---|---|

| get\_entity | entity\_id | Retrieve one entity |

| get\_neighbors | entity\_id, depth=1 | Retrieve connected neighbours |

| get\_subgraph | entity\_id, depth=2 | Retrieve nodes and relationships |

| find\_attack\_paths | source\_id, target\_id, max\_depth=3 | Find directed graph paths |

| get\_blast\_radius | entity\_id, max\_depth=3 | Find potentially reachable entities |

| get\_entity\_evidence | entity\_id | Retrieve associated events and evidence |

| get\_incident\_evidence | incident\_id | Retrieve incident-related events and evidence |

| simulate\_containment | entity\_id, excluded\_relationship\_ids | Generate a hypothetical graph without selected relationships |



\### Traversal limits



\- Neighbour depth: 1–3

\- Subgraph depth: 1–3

\- Attack path depth: 1–5

\- Blast radius depth: 1–3



Invalid depth values raise `ValueError`.



\## 4. Subgraph response format



Example:



```json

{

&#x20; "nodes": \[

&#x20;   {

&#x20;     "id": "HOST-001",

&#x20;     "type": "Host",

&#x20;     "properties": {

&#x20;       "id": "HOST-001",

&#x20;       "type": "Host"

&#x20;     }

&#x20;   }

&#x20; ],

&#x20; "edges": \[

&#x20;   {

&#x20;     "id": "REL-001",

&#x20;     "source": "HOST-001",

&#x20;     "target": "SRV-001",

&#x20;     "type": "COMMUNICATES\_WITH",

&#x20;     "properties": {

&#x20;       "relationship\_id": "REL-001"

&#x20;     }

&#x20;   }

&#x20; ],

&#x20; "metadata": {

&#x20;   "traversal\_depth": 2,

&#x20;   "total\_nodes": 1,

&#x20;   "total\_edges": 1

&#x20; }

}

```



The values above illustrate the response structure, not a guaranteed database result.



\## 5. Attack path response



Each path contains:

\- Ordered nodes

\- Ordered relationships

\- An interpretation explaining that a graph path is not proof of compromise.



Example:



```json

{

&#x20; "nodes": \[],

&#x20; "edges": \[],

&#x20; "interpretation": "Potential graph path; not proof of compromise."

}

```



\## 6. Blast radius response



```json

{

&#x20; "source\_id": "HOST-001",

&#x20; "potentially\_reachable": \[],

&#x20; "interpretation": "Graph reachability indicates potential exposure, not confirmed compromise."

}

```



Reachability must not be interpreted as confirmed compromise.



\## 7. Evidence response



Both evidence methods return a list of objects:



```json

\[

&#x20; {

&#x20;   "event": {

&#x20;     "id": "EVT-001",

&#x20;     "type": "SecurityEvent",

&#x20;     "properties": {}

&#x20;   },

&#x20;   "evidence": {

&#x20;     "id": "EVD-001",

&#x20;     "type": "Evidence",

&#x20;     "properties": {}

&#x20;   }

&#x20; }

]

```



The properties contain the available event and evidence provenance.



\## 8. Containment simulation



Example:



```python

result = graph.simulate\_containment(

&#x20;   "HOST-001",

&#x20;   \["REL-001"]

)

```



Response:



```json

{

&#x20; "nodes": \[],

&#x20; "edges": \[],

&#x20; "simulation\_only": true,

&#x20; "excluded\_relationship\_ids": \["REL-001"]

}

```



This operation is intended as a hypothetical simulation. It must not be presented as a real containment action or as modifying Neo4j.



\## 9. FastAPI integration example



Member 5 can call the service from the backend:



```python

from fastapi import APIRouter, HTTPException

from member2\_graph.src.graph\_service import GraphService



router = APIRouter(prefix="/graph", tags=\["Graph Intelligence"])





@router.get("/entity/{entity\_id}")

def get\_entity(entity\_id: str):

&#x20;   graph = GraphService()

&#x20;   try:

&#x20;       result = graph.get\_entity(entity\_id)

&#x20;       if result is None:

&#x20;           raise HTTPException(status\_code=404, detail="Entity not found")

&#x20;       return result

&#x20;   finally:

&#x20;       graph.close()





@router.get("/subgraph/{entity\_id}")

def get\_subgraph(entity\_id: str, depth: int = 2):

&#x20;   graph = GraphService()

&#x20;   try:

&#x20;       return graph.get\_subgraph(entity\_id, depth)

&#x20;   except ValueError as error:

&#x20;       raise HTTPException(status\_code=400, detail=str(error))

&#x20;   finally:

&#x20;       graph.close()





@router.get("/blast-radius/{entity\_id}")

def get\_blast\_radius(entity\_id: str, depth: int = 3):

&#x20;   graph = GraphService()

&#x20;   try:

&#x20;       return graph.get\_blast\_radius(entity\_id, depth)

&#x20;   except ValueError as error:

&#x20;       raise HTTPException(status\_code=400, detail=str(error))

&#x20;   finally:

&#x20;       graph.close()

```



These are integration examples. Member 5 should adapt the routes to the existing FastAPI application and avoid creating duplicate endpoints.



\## 10. Important interpretation and safety rules



1\. A graph path does not establish that an attack occurred.

2\. Shared IP addresses do not establish compromise.

3\. Blast radius indicates potential reachability, not confirmed impact.

4\. Containment simulation is hypothetical and does not execute network actions.

5\. Evidence provenance should be preserved when displaying investigation results.

6\. Database credentials must remain in environment variables.

7\. The frontend should communicate with FastAPI, not connect directly to Neo4j.



\## 11. Testing



Run the automated unit tests:



```powershell

python -m unittest discover -s member2\_graph/tests -v

```



The current test suite uses mocked data and does not require a live Neo4j connection.



Live database integration testing must be performed separately once Neo4j Aura connectivity is available.



\---



\*\*Module owner:\*\* Member 2 — Neo4j Graph Intelligence  

\*\*Integration consumer:\*\* Member 5 — FastAPI Backend and React Dashboard



