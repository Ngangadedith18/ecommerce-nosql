# -*- coding: utf-8 -*-
"""
Pipeline de nettoyage et d'injection — Projet NoSQL E-Commerce
============================================================
Étape 1 : Nettoyage des données brutes avec journalisation complète
Étape 2 : Injection en masse (Bulk) dans MongoDB
Étape 3 : Injection des relations dans Neo4j (UNWIND)
Étape 4 : Peuplement Redis (sessions + top ventes)
"""

import pandas as pd
import re
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
import random

# ── Dépendances tierces (pip install pymongo neo4j redis)
from pymongo import MongoClient, InsertOne, UpdateOne
from pymongo.errors import BulkWriteError
from neo4j import GraphDatabase
import redis

# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
MONGO_URI = "mongodb://localhost:27017/?directConnection=true"
NEO4J_URI = "bolt://localhost:7687"
NEO4J_USER   = "neo4j"
NEO4J_PASS   = "password"
REDIS_HOST = "localhost"
REDIS_PORT   = 6379

CSV_PATH = r"C:\ecommerce-nosql\data\ecommerce_raw_transactions_dirty.csv"
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

BULK_SIZE    = 1000   # taille des lots pour les opérations Bulk

# ─────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────
log_file = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(open(1, 'w', encoding='utf-8', closefd=False))
    ]
)
logger = logging.getLogger("pipeline")

# ─────────────────────────────────────────
# ÉTAPE 1 : NETTOYAGE
# ─────────────────────────────────────────

class DataCleaner:
    """Nettoie le CSV brut et journalise chaque anomalie rejetée."""

    ISO_RE      = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    SLASH_RE    = re.compile(r"^(\d{4})/(\d{2})/(\d{2}) (\d{2}:\d{2}:\d{2})$")
    PRICE_CFA   = re.compile(r"^([\d.]+)\s*CFA$", re.IGNORECASE)

    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.rejected_log: list[dict] = []
        self.stats = {
            "total_raw": 0,
            "duplicates": 0,
            "bad_date": 0,
            "bad_price": 0,
            "bad_quantity": 0,
            "anonymous": 0,  # conservés dans MongoDB, exclus de Neo4j
            "clean": 0,
        }

    # ── Nettoyage des dates ──────────────────
    def _parse_date(self, value: str) -> str | None:
        """Retourne une date ISO-8601 ou None si irréparable."""
        if self.ISO_RE.match(value):
            # Valider les composantes (ex : 2025-00-99 est invalide)
            try:
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
                return value
            except ValueError:
                return None
        m = self.SLASH_RE.match(value)
        if m:
            try:
                dt = datetime.strptime(f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}", "%Y-%m-%dT%H:%M:%S")
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
            except ValueError:
                return None
        return None

    # ── Nettoyage des prix ───────────────────
    def _parse_price(self, value: str) -> float | None:
        """Extrait un float valide ou None."""
        m = self.PRICE_CFA.match(str(value).strip())
        if m:
            return float(m.group(1))
        try:
            price = float(value)
            return price if price > 0 else None
        except (ValueError, TypeError):
            return None

    # ── Nettoyage des quantités ──────────────
    def _parse_qty(self, value) -> int | None:
        try:
            qty = int(value)
            return qty if qty > 0 else None
        except (ValueError, TypeError):
            return None

    def _reject(self, row: dict, reason: str):
        self.rejected_log.append({
            "transaction_id": row.get("transaction_id"),
            "reason": reason,
            "raw": row
        })
        self.stats[reason] = self.stats.get(reason, 0) + 1

    # ── Pipeline principal ───────────────────
    def clean(self) -> tuple[pd.DataFrame, pd.DataFrame]:
        """
        Retourne (df_all_clean, df_identified_clean).
        df_all_clean       → injection MongoDB (avec les anonymes)
        df_identified_clean→ injection Neo4j (sans les anonymes)
        """
        logger.info("Lecture du CSV brut…")
        df = pd.read_csv(self.csv_path, dtype=str)
        self.stats["total_raw"] = len(df)
        logger.info(f"  {len(df):,} lignes lues")

        # 1. Doublons stricts
        before = len(df)
        df = df.drop_duplicates()
        self.stats["duplicates"] = before - len(df)
        logger.info(f"  Doublons supprimés : {self.stats['duplicates']:,}")

        # 2. Nettoyage colonne par colonne
        clean_rows   = []
        for _, row in df.iterrows():
            r = row.to_dict()

            # Date
            date_ok = self._parse_date(str(r.get("transaction_date", "")))
            if date_ok is None:
                self._reject(r, "bad_date")
                continue
            r["transaction_date"] = date_ok

            # Prix
            price_ok = self._parse_price(r.get("unit_price", ""))
            if price_ok is None:
                self._reject(r, "bad_price")
                continue
            r["unit_price"] = price_ok

            # Quantité
            qty_ok = self._parse_qty(r.get("quantity", ""))
            if qty_ok is None:
                self._reject(r, "bad_quantity")
                continue
            r["quantity"]     = qty_ok
            r["total_amount"] = round(price_ok * qty_ok, 2)

            # Recalcul total (on écrase la valeur brute potentiellement fausse)
            r["total_amount"] = round(price_ok * qty_ok, 2)

            clean_rows.append(r)

        df_clean = pd.DataFrame(clean_rows)

        # Compter les anonymes (NaN ou vide) — conservés pour MongoDB
        anon_mask = df_clean["customer_id"].isna() | (df_clean["customer_id"].str.strip() == "")
        self.stats["anonymous"] = int(anon_mask.sum())
        self.stats["clean"]     = len(df_clean)

        df_identified = df_clean[~anon_mask].copy()

        # Sauvegarde du journal de rejet
        rejected_path = LOG_DIR / "rejected_rows.json"
        with open(rejected_path, "w", encoding="utf-8") as f:
            json.dump(self.rejected_log, f, ensure_ascii=False, indent=2, default=str)

        logger.info("─── Bilan nettoyage ───────────────────────────")
        for k, v in self.stats.items():
            logger.info(f"  {k:<20}: {v:,}")
        logger.info(f"  Journal rejet        : {rejected_path}")
        logger.info("───────────────────────────────────────────────")

        return df_clean, df_identified


# ─────────────────────────────────────────
# ÉTAPE 2 : INJECTION MONGODB (BULK)
# ─────────────────────────────────────────

class MongoInjector:
    """Injection en masse dans MongoDB via Replica Set."""

    def __init__(self, uri: str):
        self.client = MongoClient(uri)
        self.db = self.client["ecommerce"]
        logger.info(f"MongoDB connecté — Replica Set : {self.client.topology_description.topology_type}")

    def inject_transactions(self, df: pd.DataFrame):
        """Insère les transactions par lots de BULK_SIZE."""
        col = self.db["transactions"]
        col.create_index("transaction_id", unique=True)
        col.create_index("customer_id")
        col.create_index("product_id")
        col.create_index([("transaction_date", -1)])
        col.create_index("product_category")

        total_inserted = 0
        total_errors   = 0
        records = df.to_dict("records")

        for i in range(0, len(records), BULK_SIZE):
            batch = records[i : i + BULK_SIZE]
            ops = [InsertOne(r) for r in batch]
            try:
                result = col.bulk_write(ops, ordered=False)
                total_inserted += result.inserted_count
            except BulkWriteError as e:
                dup_count = sum(1 for err in e.details["writeErrors"] if err["code"] == 11000)
                total_errors += len(e.details["writeErrors"])
                total_inserted += e.details.get("nInserted", 0)
                if dup_count:
                    logger.warning(f"  Lot {i//BULK_SIZE+1}: {dup_count} doublons ignorés (upsert idempotent)")

        logger.info(f"MongoDB — transactions insérées : {total_inserted:,}  erreurs : {total_errors}")

    def inject_catalog(self, df: pd.DataFrame):
        """Construit et insère le catalogue de produits (agrégat par product_id)."""
        col = self.db["products"]
        col.create_index("product_id", unique=True)

        catalog = (
            df.groupby(["product_id", "product_category"])
            .agg(
                total_sales=("quantity", "sum"),
                revenue=("total_amount", "sum"),
                avg_price=("unit_price", "mean"),
                tx_count=("transaction_id", "count"),
            )
            .reset_index()
        )

        ops = [
            UpdateOne(
                {"product_id": r["product_id"]},
                {"$set": {
                    "product_id":       r["product_id"],
                    "product_category": r["product_category"],
                    "total_sales":      int(r["total_sales"]),
                    "revenue":          round(r["revenue"], 2),
                    "avg_price":        round(r["avg_price"], 2),
                    "tx_count":         int(r["tx_count"]),
                }},
                upsert=True,
            )
            for _, r in catalog.iterrows()
        ]

        for i in range(0, len(ops), BULK_SIZE):
            self.db["products"].bulk_write(ops[i : i + BULK_SIZE], ordered=False)

        logger.info(f"MongoDB — produits du catalogue : {len(catalog):,}")

    def close(self):
        self.client.close()


# ─────────────────────────────────────────
# ÉTAPE 3 : INJECTION NEO4J (UNWIND)
# ─────────────────────────────────────────

class Neo4jInjector:
    """Injection des nœuds et relations dans Neo4j via UNWIND (batch Cypher)."""

    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        logger.info("Neo4j connecté")

    def _run_batch(self, session, cypher: str, rows: list[dict]):
        session.run(cypher, rows=rows)

    def setup_constraints(self):
        with self.driver.session() as s:
            s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Customer) REQUIRE c.id IS UNIQUE")
            s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Product)  REQUIRE p.id IS UNIQUE")
            s.run("CREATE INDEX IF NOT EXISTS FOR (p:Product) ON (p.category)")
        logger.info("Neo4j — contraintes et index créés")

    def inject(self, df: pd.DataFrame):
        """Injections UNWIND pour Customers, Products et relations PURCHASED."""
        self.setup_constraints()

        # ── Clients (identifiés uniquement)
        customers = df[["customer_id"]].drop_duplicates().rename(columns={"customer_id": "id"})
        cypher_customers = """
        UNWIND $rows AS row
        MERGE (c:Customer {id: row.id})
        """

        # ── Produits
        products = (
            df[["product_id", "product_category"]]
            .drop_duplicates("product_id")
            .rename(columns={"product_id": "id", "product_category": "category"})
        )
        cypher_products = """
        UNWIND $rows AS row
        MERGE (p:Product {id: row.id})
          ON CREATE SET p.category = row.category
        """

        # ── Relations PURCHASED
        # Seulement les transactions avec customer_id valide
        relations = df.dropna(subset=["customer_id"])
        cypher_purchased = """
        UNWIND $rows AS row
        MATCH (c:Customer {id: row.customer_id})
        MATCH (p:Product  {id: row.product_id})
        MERGE (c)-[r:PURCHASED {transaction_id: row.transaction_id}]->(p)
          ON CREATE SET
            r.quantity       = row.quantity,
            r.unit_price     = row.unit_price,
            r.total_amount   = row.total_amount,
            r.date           = row.transaction_date,
            r.category       = row.product_category
        """

        with self.driver.session() as s:
            # Clients
            rows = customers.to_dict("records")
            for i in range(0, len(rows), BULK_SIZE):
                self._run_batch(s, cypher_customers, rows[i:i+BULK_SIZE])
            logger.info(f"Neo4j — clients injectés : {len(rows):,}")

            # Produits
            rows = products.to_dict("records")
            for i in range(0, len(rows), BULK_SIZE):
                self._run_batch(s, cypher_products, rows[i:i+BULK_SIZE])
            logger.info(f"Neo4j — produits injectés : {len(rows):,}")

            # Relations
            rows = relations.to_dict("records")
            for i in range(0, len(rows), BULK_SIZE):
                self._run_batch(s, cypher_purchased, rows[i:i+BULK_SIZE])
            logger.info(f"Neo4j — relations PURCHASED injectées : {len(rows):,}")

    def close(self):
        self.driver.close()


# ─────────────────────────────────────────
# ÉTAPE 4 : REDIS (Sessions + Top Ventes)
# ─────────────────────────────────────────

class RedisInjector:
    """Peuple Redis avec des sessions simulées et le top des ventes en temps réel."""

    SESSION_TTL = 3600  # 1 heure

    def __init__(self, host: str, port: int):
        self.r = redis.Redis(host=host, port=port, decode_responses=True)
        logger.info("Redis connecté")

    def seed_sessions(self, df: pd.DataFrame, sample_size: int = 500):
        """Crée des sessions utilisateur simulées avec TTL."""
        customers = df["customer_id"].dropna().unique()[:sample_size]
        pipe = self.r.pipeline(transaction=False)

        for cid in customers:
            session_key = f"session:{cid}"
            session_data = {
                "customer_id":  cid,
                "login_at":     datetime.now().isoformat(),
                "cart":         json.dumps([]),
                "last_action":  "login",
            }
            pipe.hset(session_key, mapping=session_data)
            pipe.expire(session_key, self.SESSION_TTL)

        pipe.execute()
        logger.info(f"Redis — sessions créées : {len(customers):,} (TTL {self.SESSION_TTL}s)")

    def seed_top_sales(self, df: pd.DataFrame):
        """Peuple un Sorted Set 'top_sales' avec le CA par produit."""
        top = (
            df.groupby("product_id")["total_amount"]
            .sum()
            .reset_index()
            .rename(columns={"total_amount": "revenue"})
        )

        pipe = self.r.pipeline(transaction=False)
        for _, row in top.iterrows():
            pipe.zadd("top_sales", {row["product_id"]: row["revenue"]})
        pipe.execute()
        logger.info(f"Redis — top_sales peuplé avec {len(top):,} produits")

    def seed_category_counters(self, df: pd.DataFrame):
        """Compteurs de ventes par catégorie (Hash)."""
        cats = df.groupby("product_category")["quantity"].sum()
        pipe = self.r.pipeline(transaction=False)
        for cat, qty in cats.items():
            pipe.hset("sales_by_category", cat, int(qty))
        pipe.execute()
        logger.info(f"Redis — compteurs catégories : {cats.to_dict()}")


# ─────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────

def main():
    logger.info("══════════ DÉMARRAGE DU PIPELINE ══════════")

    # ── 1. Nettoyage
    cleaner = DataCleaner(CSV_PATH)
    df_all, df_identified = cleaner.clean()

    # ── 2. MongoDB
    mongo = MongoInjector(MONGO_URI)
    mongo.inject_transactions(df_all)       # inclut les anonymes
    mongo.inject_catalog(df_all)
    mongo.close()

    # ── 3. Neo4j (seulement transactions identifiées)
    neo4j = Neo4jInjector(NEO4J_URI, NEO4J_USER, NEO4J_PASS)
    neo4j.inject(df_identified)
    neo4j.close()

    # ── 4. Redis
    redis_inj = RedisInjector(REDIS_HOST, REDIS_PORT)
    redis_inj.seed_sessions(df_identified)
    redis_inj.seed_top_sales(df_all)
    redis_inj.seed_category_counters(df_all)

    logger.info("══════════ PIPELINE TERMINÉ ══════════")
    logger.info(f"Log complet : {log_file}")


if __name__ == "__main__":
    main()