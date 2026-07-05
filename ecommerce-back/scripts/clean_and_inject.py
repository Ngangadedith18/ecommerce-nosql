# -*- coding: utf-8 -*-
"""
Pipeline de nettoyage et d'injection — Projet NoSQL E-Commerce
============================================================
Étape 1 : Nettoyage des données brutes avec journalisation complète (errors.log)
Étape 2 : Injection en masse (Bulk) dans MongoDB — structure Commande avec items[]
Étape 3 : Injection des relations dans Neo4j (UNWIND en bloc)
Étape 4 : Peuplement Redis (Top produits ZINCRBY + sessions TTL)
"""

import pandas as pd
import re
import logging
import json
from datetime import datetime, timedelta
from pathlib import Path
import random

# pip install pymongo neo4j redis
from pymongo import MongoClient, InsertOne, UpdateOne
from pymongo.errors import BulkWriteError
from neo4j import GraphDatabase
import redis

# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
MONGO_URI  = "mongodb://localhost:27017/?directConnection=true"
NEO4J_URI  = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "password"
REDIS_HOST = "localhost"
REDIS_PORT = 6379

CSV_PATH   = r"C:\ecommerce-nosql\ecommerce-back\data\ecommerce_raw_transactions_dirty.csv"
LOG_DIR    = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

BULK_SIZE  = 1000

# ─────────────────────────────────────────
# LOGGING — pipeline.log + errors.log
# ─────────────────────────────────────────
log_file   = LOG_DIR / f"pipeline_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
error_file = LOG_DIR / "errors.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(open(1, 'w', encoding='utf-8', closefd=False))
    ]
)
logger = logging.getLogger("pipeline")

# Logger dédié aux erreurs (errors.log)
error_logger = logging.getLogger("errors")
error_handler = logging.FileHandler(error_file, encoding="utf-8")
error_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
error_logger.addHandler(error_handler)
error_logger.setLevel(logging.ERROR)


# ─────────────────────────────────────────
# ÉTAPE 1 : NETTOYAGE
# ─────────────────────────────────────────

class DataCleaner:
    """
    Nettoie le CSV brut et journalise chaque anomalie.
    - errors.log  : anomalies de format (dates, prix corrompus)
    - rejected_rows.json : toutes les lignes rejetées avec raison
    """

    ISO_RE   = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$")
    SLASH_RE = re.compile(r"^(\d{4})/(\d{2})/(\d{2}) (\d{2}:\d{2}:\d{2})$")
    PRICE_CFA = re.compile(r"^([\d.]+)\s*CFA$", re.IGNORECASE)

    def __init__(self, csv_path: str):
        self.csv_path = csv_path
        self.rejected_log: list = []
        self.stats = {
            "total_raw": 0,
            "duplicates": 0,
            "bad_date": 0,
            "bad_price": 0,
            "bad_quantity": 0,
            "anonymous": 0,
            "clean": 0,
        }

    def _parse_date(self, value: str):
        """Retourne une date ISO-8601 ou None si irréparable."""
        try:
            if self.ISO_RE.match(value):
                datetime.strptime(value, "%Y-%m-%dT%H:%M:%S")
                return value
            m = self.SLASH_RE.match(value)
            if m:
                dt = datetime.strptime(
                    f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{m.group(4)}",
                    "%Y-%m-%dT%H:%M:%S"
                )
                return dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass
        return None

    def _parse_price(self, value):
        """Extrait un float valide ou None. Gère '25000 CFA' et -99.99."""
        try:
            m = self.PRICE_CFA.match(str(value).strip())
            if m:
                return float(m.group(1))
            price = float(value)
            return price if price > 0 else None
        except (ValueError, TypeError):
            return None

    def _parse_qty(self, value):
        """Retourne un entier > 0 ou None."""
        try:
            qty = int(value)
            return qty if qty > 0 else None
        except (ValueError, TypeError):
            return None

    def _reject(self, row: dict, reason: str):
        """Journalise le rejet dans rejected_rows.json et errors.log si format corrompu."""
        self.rejected_log.append({
            "transaction_id": row.get("transaction_id"),
            "reason": reason,
            "raw": row
        })
        self.stats[reason] = self.stats.get(reason, 0) + 1
        # Les erreurs de format vont aussi dans errors.log
        if reason in ("bad_date", "bad_price"):
            error_logger.error(json.dumps({
                "transaction_id": row.get("transaction_id"),
                "reason": reason,
                "raw_value": row.get("transaction_date") if reason == "bad_date" else row.get("unit_price")
            }, ensure_ascii=False))

    def clean(self):
        """
        Retourne (df_all_clean, df_identified_clean).
        df_all_clean        → injection MongoDB (avec les anonymes)
        df_identified_clean → injection Neo4j (sans les anonymes)
        """
        logger.info("Lecture du CSV brut…")
        try:
            df = pd.read_csv(self.csv_path, dtype=str)
        except FileNotFoundError:
            logger.error(f"Fichier introuvable : {self.csv_path}")
            raise

        self.stats["total_raw"] = len(df)
        logger.info(f"  {len(df):,} lignes lues")

        # 1. Suppression des doublons stricts
        before = len(df)
        df = df.drop_duplicates()
        self.stats["duplicates"] = before - len(df)
        logger.info(f"  Doublons supprimés : {self.stats['duplicates']:,}")

        # 2. Nettoyage ligne par ligne avec try-catch systématique
        clean_rows = []
        for _, row in df.iterrows():
            try:
                r = row.to_dict()

                # Validation de la date
                date_ok = self._parse_date(str(r.get("transaction_date", "")))
                if date_ok is None:
                    self._reject(r, "bad_date")
                    continue
                r["transaction_date"] = date_ok

                # Validation du prix
                price_ok = self._parse_price(r.get("unit_price", ""))
                if price_ok is None:
                    self._reject(r, "bad_price")
                    continue
                r["unit_price"] = price_ok

                # Validation de la quantité
                qty_ok = self._parse_qty(r.get("quantity", ""))
                if qty_ok is None:
                    self._reject(r, "bad_quantity")
                    continue
                r["quantity"]     = qty_ok
                r["total_amount"] = round(price_ok * qty_ok, 2)

                clean_rows.append(r)

            except Exception as e:
                # Sécurité : aucune exception ne plante le pipeline
                error_logger.error(json.dumps({
                    "transaction_id": row.get("transaction_id", "UNKNOWN"),
                    "reason": "unexpected_error",
                    "error": str(e)
                }))
                logger.warning(f"Ligne ignorée (erreur inattendue) : {row.get('transaction_id')} — {e}")

        df_clean = pd.DataFrame(clean_rows)

        # Comptage des anonymes
        if df_clean.empty or "customer_id" not in df_clean.columns:
            anon_mask = pd.Series([], dtype=bool)
        else:
            anon_mask = df_clean["customer_id"].isna() | (df_clean["customer_id"].astype(str).str.strip() == "")
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
        logger.info(f"  Journal erreurs      : {error_file}")
        logger.info("───────────────────────────────────────────────")

        return df_clean, df_identified


# ─────────────────────────────────────────
# ÉTAPE 2 : INJECTION MONGODB (BULK)
# Structure : Commande unique avec tableau items[]
# ─────────────────────────────────────────

class MongoInjector:
    """
    Injection en masse dans MongoDB.
    Chaque document respecte le format demandé :
    {
        "_id": "TX-2026000123",
        "customer_id": "CUST-45892",
        "date": "2025-03-12T14:22:01",
        "items": [
            { "product_id": "PROD-101", "category": "Électronique",
              "quantity": 1, "unit_price": 450.00 }
        ],
        "total_amount": 450.00
    }
    """

    def __init__(self, uri: str):
        try:
            self.client = MongoClient(uri, serverSelectionTimeoutMS=5000)
            self.db = self.client["ecommerce"]
            self.client.admin.command("ping")
            logger.info("MongoDB connecté")
        except Exception as e:
            logger.error(f"Connexion MongoDB échouée : {e}")
            raise

    def _build_order_document(self, row: dict) -> dict:
        """Transforme une ligne CSV en document Commande avec items[]."""
        return {
            "_id":          row["transaction_id"],
            "customer_id":  row.get("customer_id") or None,
            "date":         row["transaction_date"],
            "items": [{
                "product_id": row["product_id"],
                "category":   row["product_category"],
                "quantity":   row["quantity"],
                "unit_price": row["unit_price"],
            }],
            "total_amount": row["total_amount"],
            "source":       "pipeline_v2",
        }

    def inject_transactions(self, df: pd.DataFrame):
        """Insère les commandes par lots de BULK_SIZE."""
        col = self.db["transactions"]

        try:
            col.create_index("customer_id")
            col.create_index("items.product_id")
            col.create_index([("date", -1)])
            col.create_index("items.category")
        except Exception as e:
            logger.warning(f"Index déjà existants : {e}")

        records = df.to_dict("records")
        total_inserted = 0
        total_errors   = 0

        for i in range(0, len(records), BULK_SIZE):
            batch = records[i: i + BULK_SIZE]
            ops = []
            for r in batch:
                try:
                    doc = self._build_order_document(r)
                    ops.append(InsertOne(doc))
                except Exception as e:
                    logger.warning(f"Document ignoré : {r.get('transaction_id')} — {e}")
                    total_errors += 1

            if not ops:
                continue

            try:
                result = self.db["transactions"].bulk_write(ops, ordered=False)
                total_inserted += result.inserted_count
            except BulkWriteError as e:
                dup_count = sum(1 for err in e.details["writeErrors"] if err["code"] == 11000)
                total_errors += len(e.details["writeErrors"])
                total_inserted += e.details.get("nInserted", 0)
                if dup_count:
                    logger.warning(f"Lot {i//BULK_SIZE+1} : {dup_count} doublons ignorés")
            except Exception as e:
                logger.error(f"Erreur bulk_write lot {i//BULK_SIZE+1} : {e}")
                error_logger.error(json.dumps({"step": "mongodb_bulk", "error": str(e)}))

        logger.info(f"MongoDB — transactions insérées : {total_inserted:,}  erreurs : {total_errors}")

    def inject_catalog(self, df: pd.DataFrame):
        """Construit et insère le catalogue de produits (agrégat par product_id)."""
        try:
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
                self.db["products"].bulk_write(ops[i: i + BULK_SIZE], ordered=False)

            logger.info(f"MongoDB — produits du catalogue : {len(catalog):,}")

        except Exception as e:
            logger.error(f"Erreur injection catalogue : {e}")
            error_logger.error(json.dumps({"step": "mongodb_catalog", "error": str(e)}))

    def close(self):
        self.client.close()


# ─────────────────────────────────────────
# ÉTAPE 3 : INJECTION NEO4J (UNWIND)
# ─────────────────────────────────────────

class Neo4jInjector:
    """Injection des nœuds et relations dans Neo4j via UNWIND (batch Cypher)."""

    def __init__(self, uri: str, user: str, password: str):
        try:
            self.driver = GraphDatabase.driver(uri, auth=(user, password))
            with self.driver.session() as s:
                s.run("RETURN 1")
            logger.info("Neo4j connecté")
        except Exception as e:
            logger.error(f"Connexion Neo4j échouée : {e}")
            raise

    def setup_constraints(self):
        try:
            with self.driver.session() as s:
                s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (c:Customer) REQUIRE c.id IS UNIQUE")
                s.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Product)  REQUIRE p.id IS UNIQUE")
                s.run("CREATE INDEX IF NOT EXISTS FOR (p:Product) ON (p.category)")
            logger.info("Neo4j — contraintes et index créés")
        except Exception as e:
            logger.warning(f"Contraintes Neo4j : {e}")

    def inject(self, df: pd.DataFrame):
        """Injections UNWIND pour Customers, Products et relations PURCHASED."""
        self.setup_constraints()

        cypher_customers = """
        UNWIND $rows AS row
        MERGE (c:Customer {id: row.id})
        """
        cypher_products = """
        UNWIND $rows AS row
        MERGE (p:Product {id: row.id})
          ON CREATE SET p.category = row.category
        """
        cypher_purchased = """
        UNWIND $rows AS row
        MATCH (c:Customer {id: row.customer_id})
        MATCH (p:Product  {id: row.product_id})
        MERGE (c)-[r:PURCHASED {transaction_id: row.transaction_id}]->(p)
          ON CREATE SET
            r.quantity     = row.quantity,
            r.unit_price   = row.unit_price,
            r.total_amount = row.total_amount,
            r.date         = row.transaction_date,
            r.category     = row.product_category
        """

        try:
            with self.driver.session() as s:
                # Clients
                customers = df[["customer_id"]].drop_duplicates().rename(columns={"customer_id": "id"})
                rows = customers.to_dict("records")
                for i in range(0, len(rows), BULK_SIZE):
                    s.run(cypher_customers, rows=rows[i:i+BULK_SIZE])
                logger.info(f"Neo4j — clients injectés : {len(rows):,}")

                # Produits
                products = (
                    df[["product_id", "product_category"]]
                    .drop_duplicates("product_id")
                    .rename(columns={"product_id": "id", "product_category": "category"})
                )
                rows = products.to_dict("records")
                for i in range(0, len(rows), BULK_SIZE):
                    s.run(cypher_products, rows=rows[i:i+BULK_SIZE])
                logger.info(f"Neo4j — produits injectés : {len(rows):,}")

                # Relations PURCHASED
                relations = df.dropna(subset=["customer_id"]).to_dict("records")
                for i in range(0, len(relations), BULK_SIZE):
                    s.run(cypher_purchased, rows=relations[i:i+BULK_SIZE])
                logger.info(f"Neo4j — relations PURCHASED injectées : {len(relations):,}")

        except Exception as e:
            logger.error(f"Erreur injection Neo4j : {e}")
            error_logger.error(json.dumps({"step": "neo4j_inject", "error": str(e)}))

    def close(self):
        self.driver.close()


# ─────────────────────────────────────────
# ÉTAPE 4 : REDIS
# Top produits ZINCRBY pendant l'ingestion + sessions TTL
# ─────────────────────────────────────────

class RedisInjector:
    """
    Peuple Redis :
    - top_products : Sorted Set incrémenté par quantité vendue (ZINCRBY)
    - sessions     : Hash avec TTL de 30 minutes
    - sales_by_category : Hash compteur par catégorie
    """

    SESSION_TTL = 1800  # 30 minutes comme demandé

    def __init__(self, host: str, port: int):
        try:
            self.r = redis.Redis(host=host, port=port, decode_responses=True)
            self.r.ping()
            logger.info("Redis connecté")
        except Exception as e:
            logger.error(f"Connexion Redis échouée : {e}")
            raise

    def seed_top_products(self, df: pd.DataFrame):
        """
        Remplit le Sorted Set 'top_products' avec ZINCRBY.
        À chaque ligne, on incrémente le score du produit par sa quantité.
        C'est exactement ce qui doit se passer pendant l'ingestion.
        """
        try:
            pipe = self.r.pipeline(transaction=False)
            for _, row in df.iterrows():
                try:
                    pipe.zincrby("top_products", row["quantity"], row["product_id"])
                except Exception as e:
                    logger.warning(f"ZINCRBY ignoré pour {row.get('product_id')} : {e}")

            pipe.execute()

            # Vérification du top 5
            top5 = self.r.zrevrange("top_products", 0, 4, withscores=True)
            logger.info(f"Redis — top_products peuplé. Top 5 :")
            for pid, score in top5:
                logger.info(f"  {pid} : {int(score)} unités vendues")

        except Exception as e:
            logger.error(f"Erreur seed_top_products : {e}")
            error_logger.error(json.dumps({"step": "redis_top_products", "error": str(e)}))

    def seed_sessions(self, df: pd.DataFrame, sample_size: int = 500):
        """
        Crée des sessions utilisateur simulées avec TTL de 30 minutes.
        Simule les utilisateurs actuellement en ligne avec un panier actif.
        """
        try:
            customers = df["customer_id"].dropna().unique()[:sample_size]
            pipe = self.r.pipeline(transaction=False)

            for cid in customers:
                session_key = f"session:{cid}"
                session_data = {
                    "customer_id": cid,
                    "login_at":    datetime.now().isoformat(),
                    "cart":        json.dumps([]),
                    "last_action": "login",
                }
                pipe.hset(session_key, mapping=session_data)
                pipe.expire(session_key, self.SESSION_TTL)

            pipe.execute()
            logger.info(f"Redis — sessions créées : {len(customers):,} (TTL {self.SESSION_TTL}s = 30 min)")

        except Exception as e:
            logger.error(f"Erreur seed_sessions : {e}")
            error_logger.error(json.dumps({"step": "redis_sessions", "error": str(e)}))

    def seed_category_counters(self, df: pd.DataFrame):
        """Compteurs de ventes par catégorie (Hash)."""
        try:
            pipe = self.r.pipeline(transaction=False)
            cats = df.groupby("product_category")["quantity"].sum()
            for cat, qty in cats.items():
                pipe.hset("sales_by_category", cat, int(qty))
            pipe.execute()
            logger.info(f"Redis — compteurs catégories : {cats.to_dict()}")
        except Exception as e:
            logger.error(f"Erreur seed_category_counters : {e}")


# ─────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────

def main():
    logger.info("══════════ DÉMARRAGE DU PIPELINE ══════════")

    # Étape 1 — Nettoyage
    try:
        cleaner = DataCleaner(CSV_PATH)
        df_all, df_identified = cleaner.clean()
    except Exception as e:
        logger.error(f"Nettoyage échoué : {e}")
        return

    # Étape 2 — MongoDB
    try:
        mongo = MongoInjector(MONGO_URI)
        mongo.inject_transactions(df_all)
        mongo.inject_catalog(df_all)
        mongo.close()
    except Exception as e:
        logger.error(f"Injection MongoDB échouée : {e}")

    # Étape 3 — Neo4j
    try:
        neo4j = Neo4jInjector(NEO4J_URI, NEO4J_USER, NEO4J_PASS)
        neo4j.inject(df_identified)
        neo4j.close()
    except Exception as e:
        logger.error(f"Injection Neo4j échouée : {e}")

    # Étape 4 — Redis
    try:
        redis_inj = RedisInjector(REDIS_HOST, REDIS_PORT)
        redis_inj.seed_top_products(df_all)        # ZINCRBY par quantité
        redis_inj.seed_sessions(df_identified)     # TTL 30 min
        redis_inj.seed_category_counters(df_all)
    except Exception as e:
        logger.error(f"Injection Redis échouée : {e}")

    logger.info("══════════ PIPELINE TERMINÉ ══════════")
    logger.info(f"Log complet   : {log_file}")
    logger.info(f"Erreurs format: {error_file}")


if __name__ == "__main__":
    main()