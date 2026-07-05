"""
API REST — Plateforme E-Commerce NoSQL
=======================================
FastAPI · MongoDB · Neo4j · Redis

Endpoints :
  GET  /products/top                   → Top N produits par CA (MongoDB agregation)
  GET  /customers/{id}/orders          → Historique commandes avec stats (MongoDB)
  GET  /analytics/revenue-by-category  → CA par catégorie + tendance (MongoDB)
  GET  /recommendations/{customer_id}  → Recommandations 2-3 niveaux (Neo4j Cypher)
  GET  /sales/realtime-top             → Top ventes en temps réel (Redis Sorted Set)
  POST /sessions                       → Créer/rafraîchir session (Redis)
  GET  /sessions/{customer_id}         → Lire une session (Redis)

Rate Limiting via Redis (sliding window) : 60 req / minute / IP
"""

from __future__ import annotations

import os
import subprocess
import sys
import asyncio
import tempfile
import time
import json
import concurrent.futures
import threading
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Query, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from pymongo import MongoClient
from pymongo.collection import Collection
from neo4j import GraphDatabase, AsyncGraphDatabase
import redis.asyncio as aioredis

from datetime import datetime
from fastapi.responses import StreamingResponse
from fastapi import UploadFile, File


# ─────────────────────────────────────────
# CONFIGURATION (variables d'environnement)
# ─────────────────────────────────────────
MONGO_URI   = "mongodb://localhost:27017/?directConnection=true"
NEO4J_URI   = "bolt://localhost:7687"
NEO4J_USER  = "neo4j"
NEO4J_PASS  = "password"
REDIS_URL   = "redis://localhost:6379"

RATE_LIMIT_MAX    = 60    # requêtes max
RATE_LIMIT_WINDOW = 60    # secondes
SESSION_TTL       = 3600  # 1 h


# ─────────────────────────────────────────
# CONNEXIONS (lifespan FastAPI)
# ─────────────────────────────────────────
class AppState:
    mongo:  MongoClient
    neo4j:  object
    redis:  aioredis.Redis

app_state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Démarrage
    app_state.mongo = MongoClient(MONGO_URI)
    app_state.neo4j = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    app_state.redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    yield
    # Arrêt
    app_state.mongo.close()
    app_state.neo4j.close()
    await app_state.redis.aclose()


app = FastAPI(
    title="E-Commerce NoSQL API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────
# RATE LIMITING (sliding window Redis)
# ─────────────────────────────────────────

async def rate_limit(request: Request):
    """
    Sliding window counter via Redis.
    Clé : ratelimit:<ip>  —  TTL : RATE_LIMIT_WINDOW secondes
    """
    ip  = request.client.host
    key = f"ratelimit:{ip}"
    r   = app_state.redis

    # Incrément atomique
    count = await r.incr(key)
    if count == 1:
        await r.expire(key, RATE_LIMIT_WINDOW)

    if count > RATE_LIMIT_MAX:
        ttl = await r.ttl(key)
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit dépassé. Réessayez dans {ttl}s."
        )

    return count


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def get_transactions() -> Collection:
    return app_state.mongo["ecommerce"]["transactions"]

def get_products() -> Collection:
    return app_state.mongo["ecommerce"]["products"]


# ─────────────────────────────────────────
# ENDPOINT 1 — Top produits par CA
# ─────────────────────────────────────────

@app.get("/products/top", dependencies=[Depends(rate_limit)])
async def top_products(
    n: int = Query(10, ge=1, le=100, description="Nombre de produits"),
    category: Optional[str] = Query(None, description="Filtrer par catégorie"),
):
    """Agrégation MongoDB : top N produits par chiffre d'affaires."""
    match_stage = {}
    if category:
        match_stage["product_category"] = category

    pipeline = [
        *([ {"$match": match_stage} ] if match_stage else []),
        {
            "$group": {
                "_id":           "$product_id",
                "product_id":    {"$first": "$product_id"},
                "category":      {"$first": "$product_category"},
                "total_revenue": {"$sum": "$total_amount"},
                "total_qty":     {"$sum": "$quantity"},
                "tx_count":      {"$sum": 1},
                "avg_price":     {"$avg": "$unit_price"},
            }
        },
        {"$sort":    {"total_revenue": -1}},
        {"$limit":   n},
        {"$project": {"_id": 0}},
    ]

    results = list(get_transactions().aggregate(pipeline))
    return {"count": len(results), "products": results}


# ─────────────────────────────────────────
# ENDPOINT 2 — Historique client
# ─────────────────────────────────────────

@app.get("/customers/{customer_id}/orders", dependencies=[Depends(rate_limit)])
async def customer_orders(
    customer_id: str,
    limit: int = Query(20, ge=1, le=200),
):
    """Historique des commandes d'un client + statistiques agrégées."""
    col = get_transactions()

    # Stats globales du client
    stats_pipeline = [
        {"$match": {"customer_id": customer_id}},
        {
            "$group": {
                "_id":           "$customer_id",
                "total_spent":   {"$sum": "$total_amount"},
                "order_count":   {"$sum": 1},
                "avg_basket":    {"$avg": "$total_amount"},
                "categories":    {"$addToSet": "$product_category"},
                "first_order":   {"$min": "$transaction_date"},
                "last_order":    {"$max": "$transaction_date"},
            }
        },
    ]
    stats = list(col.aggregate(stats_pipeline))
    if not stats:
        raise HTTPException(status_code=404, detail=f"Client '{customer_id}' introuvable")

    # Dernières commandes
    orders = list(
        col.find(
            {"customer_id": customer_id},
            {"_id": 0},
        )
        .sort("transaction_date", -1)
        .limit(limit)
    )

    return {
        "customer_id": customer_id,
        "stats":       {k: v for k, v in stats[0].items() if k != "_id"},
        "orders":      orders,
    }


# ─────────────────────────────────────────
# ENDPOINT 3 — CA par catégorie
# ─────────────────────────────────────────

@app.get("/analytics/revenue-by-category", dependencies=[Depends(rate_limit)])
async def revenue_by_category():
    """Agrégation MongoDB : CA, volume, panier moyen par catégorie."""
    pipeline = [
        {
            "$group": {
                "_id":           "$product_category",
                "revenue":       {"$sum": "$total_amount"},
                "total_qty":     {"$sum": "$quantity"},
                "tx_count":      {"$sum": 1},
                "avg_basket":    {"$avg": "$total_amount"},
                "unique_products": {"$addToSet": "$product_id"},
            }
        },
        {
            "$project": {
                "_id":             0,
                "category":        "$_id",
                "revenue":         {"$round": ["$revenue", 2]},
                "total_qty":       1,
                "tx_count":        1,
                "avg_basket":      {"$round": ["$avg_basket", 2]},
                "unique_products": {"$size": "$unique_products"},
            }
        },
        {"$sort": {"revenue": -1}},
    ]
    results = list(get_transactions().aggregate(pipeline))
    total   = sum(r["revenue"] for r in results)
    for r in results:
        r["revenue_share_pct"] = round(r["revenue"] / total * 100, 1) if total else 0
    return {"total_revenue": round(total, 2), "categories": results}


# ─────────────────────────────────────────
# ENDPOINT 4 — Recommandations Neo4j
# ─────────────────────────────────────────

@app.get("/recommendations/{customer_id}", dependencies=[Depends(rate_limit)])
async def recommendations(
    customer_id: str,
    depth: int = Query(2, ge=2, le=3, description="Profondeur : 2 ou 3 niveaux"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Algorithme de recommandation collaboratif à 2-3 niveaux de profondeur.

    Niveau 2 :
      Client → (achète) → Produit ← (achète) → AutreClient → (achète) → ProduitRecommandé

    Niveau 3 :
      + un niveau de "clients similaires à AutreClient"
    """
    if depth == 2:
        cypher = """
        MATCH (me:Customer {id: $cid})-[:PURCHASED]->(p:Product)<-[:PURCHASED]-(similar:Customer)
        WHERE similar.id <> $cid
        WITH similar, COUNT(p) AS shared_products
        ORDER BY shared_products DESC
        LIMIT 50
        MATCH (similar)-[:PURCHASED]->(recommended:Product)
        WHERE NOT EXISTS {
            MATCH (me)-[:PURCHASED]->(recommended)
        }
        WITH recommended,
            SUM(shared_products) AS score,
            COUNT(DISTINCT similar) AS recommenders
        WHERE score >= 1
        RETURN recommended.id        AS product_id,
            recommended.category  AS category,
            score                 AS relevance_score,
            recommenders          AS recommended_by_n_customers
        ORDER BY score DESC
        LIMIT $limit
        """
    else:  # depth == 3
        cypher = """
        MATCH (me:Customer {id: $cid})-[:PURCHASED]->(p:Product)<-[:PURCHASED]-(l1:Customer)
        WHERE l1.id <> $cid
        WITH me, l1, COUNT(p) AS shared_l1
        ORDER BY shared_l1 DESC LIMIT 20

        MATCH (l1)-[:PURCHASED]->(p2:Product)<-[:PURCHASED]-(l2:Customer)
        WHERE l2.id <> $cid AND l2.id <> l1.id
        WITH me, l2, COUNT(p2) AS shared_l2
        ORDER BY shared_l2 DESC LIMIT 40

        MATCH (l2)-[:PURCHASED]->(recommended:Product)
        WHERE NOT EXISTS {
            MATCH (me)-[:PURCHASED]->(recommended)
        }
        WITH recommended,
             SUM(shared_l2) AS score,
             COUNT(DISTINCT l2) AS recommenders
        RETURN recommended.id       AS product_id,
               recommended.category AS category,
               score                AS relevance_score,
               recommenders         AS recommended_by_n_customers
        ORDER BY score DESC
        LIMIT $limit
        """

    with app_state.neo4j.session() as session:
        result = session.run(cypher, cid=customer_id, limit=limit)
        records = [dict(r) for r in result]

    if not records:
        raise HTTPException(
            status_code=404,
            detail=f"Aucune recommandation trouvée pour '{customer_id}' (depth={depth})"
        )

    return {
        "customer_id":      customer_id,
        "algorithm_depth":  depth,
        "recommendations":  records,
    }


# ─────────────────────────────────────────
# ENDPOINT 5 — Top ventes temps réel (Redis)
# ─────────────────────────────────────────

@app.get("/sales/realtime-top", dependencies=[Depends(rate_limit)])
async def realtime_top_sales(
    n: int = Query(10, ge=1, le=100),
):
    """Lit le Sorted Set Redis 'top_sales' pour le classement en temps réel."""
    r = app_state.redis
    items = await r.zrevrange("top_sales", 0, n - 1, withscores=True)
    return {
        "top_sales": [
            {"rank": i + 1, "product_id": pid, "revenue": round(score, 2)}
            for i, (pid, score) in enumerate(items)
        ]
    }


# ─────────────────────────────────────────
# ENDPOINTS 6-7 — Sessions Redis
# ─────────────────────────────────────────

class SessionCreate(BaseModel):
    customer_id: str
    cart:        list = []

@app.post("/sessions", dependencies=[Depends(rate_limit)])
async def create_session(body: SessionCreate):
    """Crée ou rafraîchit une session utilisateur dans Redis."""
    r   = app_state.redis
    key = f"session:{body.customer_id}"
    data = {
        "customer_id":  body.customer_id,
        "login_at":     time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cart":         json.dumps(body.cart),
        "last_action":  "login",
    }
    await r.hset(key, mapping=data)
    await r.expire(key, SESSION_TTL)
    return {"message": "Session créée", "ttl": SESSION_TTL, "key": key}


@app.get("/sessions/{customer_id}", dependencies=[Depends(rate_limit)])
async def get_session(customer_id: str):
    """Récupère la session d'un client (ou 404 si expirée)."""
    r   = app_state.redis
    key = f"session:{customer_id}"
    data = await r.hgetall(key)
    if not data:
        raise HTTPException(status_code=404, detail="Session expirée ou inexistante")
    ttl = await r.ttl(key)
    return {**data, "ttl_remaining": ttl}


# ─────────────────────────────────────────────────────
# ENDPOINTS 8 — CA des 30 derniers jours par catégorie
# ─────────────────────────────────────────────────────
@app.get("/analytics/revenue-last-30-days", dependencies=[Depends(rate_limit)])
async def revenue_last_30_days():
    """CA par catégorie sur les 30 derniers jours avec agrégation complexe."""
    from datetime import timedelta
    date_limite = (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")

    pipeline = [
        {"$match": {"transaction_date": {"$gte": date_limite}}},
        {
            "$group": {
                "_id":           "$product_category",
                "revenue":       {"$sum": "$total_amount"},
                "total_qty":     {"$sum": "$quantity"},
                "tx_count":      {"$sum": 1},
                "avg_basket":    {"$avg": "$total_amount"},
                "unique_products": {"$addToSet": "$product_id"},
            }
        },
        {
            "$project": {
                "_id":             0,
                "category":        "$_id",
                "revenue":         {"$round": ["$revenue", 2]},
                "total_qty":       1,
                "tx_count":        1,
                "avg_basket":      {"$round": ["$avg_basket", 2]},
                "unique_products": {"$size": "$unique_products"},
            }
        },
        {"$sort": {"revenue": -1}},
    ]

    results = list(get_transactions().aggregate(pipeline))
    total = sum(r["revenue"] for r in results)
    for r in results:
        r["revenue_share_pct"] = round(r["revenue"] / total * 100, 1) if total else 0

    return {
        "periode":       "30 derniers jours",
        "date_limite":   date_limite,
        "total_revenue": round(total, 2),
        "categories":    results,
    }

# ──────────────────────────────────────────────────────────────────
# ENDPOINTS 9 — Recherche textuelle avec facettes sur le catalogue 
# ──────────────────────────────────────────────────────────────────
@app.get("/catalogue/search", dependencies=[Depends(rate_limit)])
async def search_catalogue(
    q: str = Query(..., description="Mot-clé de recherche"),
    category: Optional[str] = Query(None, description="Filtrer par catégorie"),
    prix_min: Optional[float] = Query(None, description="Prix minimum"),
    prix_max: Optional[float] = Query(None, description="Prix maximum"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Recherche textuelle avec facettes sur le catalogue.
    Recherche dans nom, description, tags, marque.
    Retourne les résultats + facettes (catégories, tranches de prix).
    """
    col = app_state.mongo["ecommerce"]["catalogue"]

    # Filtre de recherche
    match_filter = {
        "$or": [
            {"nom":         {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
            {"tags":        {"$regex": q, "$options": "i"}},
            {"marque":      {"$regex": q, "$options": "i"}},
        ]
    }
    if category:
        match_filter["categorie"] = category
    if prix_min is not None:
        match_filter["prix_base"] = {"$gte": prix_min}
    if prix_max is not None:
        match_filter.setdefault("prix_base", {})["$lte"] = prix_max

    # Agrégation avec facettes
    pipeline = [
        {"$match": match_filter},
        {
            "$facet": {
                # Résultats paginés
                "resultats": [
                    {"$project": {
                        "_id":          0,
                        "product_id":   1,
                        "nom":          1,
                        "categorie":    1,
                        "marque":       1,
                        "prix_base":    1,
                        "note_moyenne": 1,
                        "stock_total":  1,
                        "nb_variants":  {"$size": "$variants"},
                    }},
                    {"$limit": limit},
                ],
                # Facette catégories
                "facettes_categories": [
                    {"$group": {"_id": "$categorie", "count": {"$sum": 1}}},
                    {"$sort": {"count": -1}},
                ],
                # Facette tranches de prix
                "facettes_prix": [
                    {
                        "$bucket": {
                            "groupBy":    "$prix_base",
                            "boundaries": [0, 50, 100, 200, 500, 1000],
                            "default":    "1000+",
                            "output":     {"count": {"$sum": 1}},
                        }
                    }
                ],
                # Total
                "total": [{"$count": "count"}],
            }
        }
    ]

    result = list(col.aggregate(pipeline))
    if not result:
        return {"resultats": [], "facettes": {}, "total": 0}

    data = result[0]
    return {
        "query":    q,
        "total":    data["total"][0]["count"] if data["total"] else 0,
        "resultats": data["resultats"],
        "facettes": {
            "categories": [{"categorie": f["_id"], "count": f["count"]} for f in data["facettes_categories"]],
            "prix":       [{"tranche": str(f["_id"]), "count": f["count"]} for f in data["facettes_prix"]],
        }
    }

# ─────────────────────────────────────────────────────────────────────────────────────────
# Lance le pipeline de nettoyage et d'injection d'un CSV uploadé (script Python externe)
# ─────────────────────────────────────────────────────────────────────────────────────────
@app.post("/pipeline/upload")
async def upload_and_run(file: UploadFile = File(...)):
    if _pipeline_status[0]["running"]:
        return {"status": "already_running"}

    content = await file.read()
    tmp_path = f"C:/ecommerce-nosql/ecommerce-back/data/uploaded_{file.filename}"
    with open(tmp_path, "wb") as f:
        f.write(content)

    _pipeline_status[0] = {"running": True, "result": None}

    def run_in_thread():
        try:
            result = subprocess.run(
                [r"C:\Python313\python.exe",
                 r"C:\ecommerce-nosql\ecommerce-back\scripts\clean_and_inject.py",
                 "--csv", tmp_path],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=r"C:\ecommerce-nosql\ecommerce-back\scripts"
            )
            _pipeline_status[0] = {
                "running": False,
                "result": {
                    "status": "success",
                    "returncode": result.returncode,
                    "stdout": result.stdout[-3000:],
                    "stderr": result.stderr[-1000:],
                }
            }
        except Exception as e:
            _pipeline_status[0] = {
                "running": False,
                "result": {"status": "error", "message": str(e), "stdout": "", "stderr": str(e)}
            }

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    return {"status": "started", "message": "Pipeline lancé en arrière-plan avec le fichier uploadé."}


# ─────────────────────────────────────────────────────
# Lance le pipeline de nettoyage et d'injection
# ─────────────────────────────────────────────────────
_pipeline_status = [{"running": False, "result": None}]

@app.post("/pipeline/run")
async def run_pipeline():
    if _pipeline_status[0]["running"]:
        return {"status": "already_running"}
    
    _pipeline_status[0] = {"running": True, "result": None}

    def run_in_thread():
        try:
            result = subprocess.run(
                [r"C:\Python313\python.exe",
                 r"C:\ecommerce-nosql\ecommerce-back\scripts\clean_and_inject.py"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                cwd=r"C:\ecommerce-nosql\ecommerce-back\scripts"
            )
            _pipeline_status[0] = {
                "running": False,
                "result": {
                    "status": "success",
                    "returncode": result.returncode,
                    "stdout": result.stdout[-3000:],
                    "stderr": result.stderr[-1000:],
                }
            }
        except Exception as e:
            _pipeline_status[0] = {
                "running": False,
                "result": {"status": "error", "message": str(e), "stdout": "", "stderr": str(e)}
            }

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()
    return {"status": "started", "message": "Pipeline lancé en arrière-plan."}

@app.get("/pipeline/status")
async def pipeline_status():
    return _pipeline_status[0]


# ─────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────
@app.get("/health")
async def health():
    """Vérifie la connectivité des trois bases."""
    checks = {}

    # MongoDB
    try:
        app_state.mongo.admin.command("ping")
        rs = app_state.mongo.admin.command("replSetGetStatus")
        checks["mongodb"] = {
            "status": "ok",
            "replicaSet": rs.get("set"),
            "members": [
                {"name": m["name"], "state": m["stateStr"]}
                for m in rs.get("members", [])
            ],
        }
    except Exception as e:
        checks["mongodb"] = {"status": "error", "detail": str(e)}

    # Neo4j
    try:
        with app_state.neo4j.session() as s:
            s.run("RETURN 1")
        checks["neo4j"] = {"status": "ok"}
    except Exception as e:
        checks["neo4j"] = {"status": "error", "detail": str(e)}

    # Redis
    try:
        await app_state.redis.ping()
        checks["redis"] = {"status": "ok"}
    except Exception as e:
        checks["redis"] = {"status": "error", "detail": str(e)}

    overall = "ok" if all(v["status"] == "ok" for v in checks.values()) else "degraded"
    return {"overall": overall, **checks}

# ─────────────────────────────────────────
# Haute disponibilité MongoDB (Replica Set)
# ─────────────────────────────────────────
@app.get("/mongodb/replicaset")
async def replicaset_status():
    from pymongo import MongoClient
    members = []
    nodes = [("mongo1", 27017), ("mongo2", 27018), ("mongo3", 27019)]
    for name, port in nodes:
        try:
            c = MongoClient(
                f"mongodb://localhost:{port}/?directConnection=true",
                serverSelectionTimeoutMS=2000
            )
            info = c.admin.command("isMaster")
            state = "PRIMARY" if info.get("ismaster") else "SECONDARY"
            members.append({"name": f"{name}:{port}", "state": state, "health": 1, "uptime": 0})
            c.close()
        except:
            members.append({"name": f"{name}:{port}", "state": "DOWN", "health": 0, "uptime": 0})
    primary = next((m["name"] for m in members if m["state"] == "PRIMARY"), None)
    return {"replicaSet": "rs0", "members": members, "primary": primary}

# ─────────────────────────────────────────
# Haute disponibilité MongoDB (Replica Set)
# ─────────────────────────────────────────
@app.post("/mongodb/failover/{action}/{node}")
async def mongodb_failover(action: str, node: str):
    if action not in ["stop", "start"]:
        raise HTTPException(status_code=400, detail="Action invalide")
    if node not in ["mongo1", "mongo2", "mongo3"]:
        raise HTTPException(status_code=400, detail="Nœud invalide")
    try:
        result = subprocess.run(
            ["docker", action, node],
            capture_output=True, text=True, timeout=15
        )
        return {
            "action": action,
            "node": node,
            "success": result.returncode == 0,
            "message": result.stdout or result.stderr
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))