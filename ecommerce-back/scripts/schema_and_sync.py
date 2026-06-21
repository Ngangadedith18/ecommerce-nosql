# -*- coding: utf-8 -*-
"""
Schéma enrichi + Pipeline de synchronisation — Projet NoSQL E-Commerce
=======================================================================
1. Création du schéma MongoDB optimisé (catalogue avec variantes tailles/couleurs)
2. Pipeline de synchronisation asynchrone simulant un achat :
   - Mise à jour du stock dans MongoDB
   - Publication d'un événement dans Redis (Pub/Sub + Sorted Set)
   - Création de la relation [:PURCHASED] dans Neo4j
"""

import asyncio
import json
import random
import logging
from datetime import datetime

import motor.motor_asyncio
from pymongo import UpdateOne
from neo4j import AsyncGraphDatabase
import redis.asyncio as aioredis

# ─────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────
MONGO_URI  = "mongodb://localhost:27017/?directConnection=true"
NEO4J_URI  = "bolt://localhost:7687"
NEO4J_USER = "neo4j"
NEO4J_PASS = "password"
REDIS_HOST = "localhost"
REDIS_PORT = 6379

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(open(1, 'w', encoding='utf-8', closefd=False))]
)
logger = logging.getLogger("sync_pipeline")


# ─────────────────────────────────────────
# GÉNÉRATION DU CATALOGUE AVEC VARIANTES
# ─────────────────────────────────────────

def generer_produits(n=10):
    """
    Génère n produits avec sous-documents variantes (tailles x couleurs).
    C'est le schéma MongoDB optimisé : tout dans un seul document.
    """
    categories = ["Mode", "Sport", "Electronique", "Maison", "Beaute"]
    tailles    = ["XS", "S", "M", "L", "XL"]
    couleurs   = [
        ("NOI", "Noir",   "#000000"),
        ("BLA", "Blanc",  "#FFFFFF"),
        ("ROU", "Rouge",  "#FF0000"),
        ("BLE", "Bleu",   "#0000FF"),
        ("VER", "Vert",   "#008000"),
    ]

    produits = []
    for i in range(1, n + 1):
        pid      = f"PROD-{i:03d}"
        cat      = random.choice(categories)
        prix     = round(random.uniform(10, 300), 2)

        # Sous-documents variantes : chaque combinaison taille/couleur
        variants = []
        for taille in random.sample(tailles, k=random.randint(2, 4)):
            for code, nom, hex_c in random.sample(couleurs, k=random.randint(1, 3)):
                sku = f"{pid}-{taille}-{code}"
                variants.append({
                    "sku":       sku,
                    "taille":    taille,
                    "couleur":   nom,
                    "hex_code":  hex_c,
                    "stock":     random.randint(5, 100),
                    "prix":      round(prix * random.uniform(0.9, 1.1), 2),
                    "poids_kg":  round(random.uniform(0.1, 2.0), 2),
                    "images":    [f"img/{sku.lower()}.jpg"],
                })

        produits.append({
            "product_id":   pid,
            "nom":          f"Produit {pid}",
            "categorie":    cat,
            "marque":       f"Marque{i}",
            "description":  f"Description du produit {pid}",
            "prix_base":    prix,
            "devise":       "XOF",
            "variants":     variants,          # <-- sous-documents
            "stock_total":  sum(v["stock"] for v in variants),
            "note_moyenne": round(random.uniform(3.0, 5.0), 1),
            "nb_avis":      random.randint(0, 500),
            "tags":         [cat.lower(), "nouveau"],
            "actif":        True,
            "cree_le":      datetime.now().isoformat(),
            "mis_a_jour":   datetime.now().isoformat(),
        })
    return produits


# ─────────────────────────────────────────
# SETUP MONGODB — COLLECTIONS + INDEX
# ─────────────────────────────────────────

async def setup_schema(db):
    """Crée les collections catalogue et orders avec leurs index."""

    # ── Collection catalogue
    try:
        await db.create_collection("catalogue")
    except Exception:
        pass  # existe déjà

    col_cat = db["catalogue"]
    await col_cat.create_index("product_id", unique=True)
    await col_cat.create_index("categorie")
    await col_cat.create_index("tags")
    await col_cat.create_index("variants.sku")
    await col_cat.create_index([("prix_base", 1), ("note_moyenne", -1)])
    logger.info("Index catalogue créés")

    # ── Collection orders (commandes historiques dénormalisées)
    try:
        await db.create_collection("orders")
    except Exception:
        pass

    col_ord = db["orders"]
    await col_ord.create_index("order_id", unique=True)
    await col_ord.create_index("customer_id")
    await col_ord.create_index([("date_commande", -1)])
    await col_ord.create_index("statut")
    await col_ord.create_index("items.product_id")
    logger.info("Index orders créés")

    # ── Insertion des produits avec variantes
    produits = generer_produits(10)
    ops = [
        UpdateOne(
            {"product_id": p["product_id"]},
            {"$set": p},
            upsert=True
        )
        for p in produits
    ]
    await col_cat.bulk_write(ops)
    logger.info(f"Catalogue : {len(produits)} produits insérés avec variantes tailles/couleurs")

    # Retourne les SKUs existants pour la simulation d'achats
    skus_disponibles = []
    async for prod in col_cat.find({"stock_total": {"$gt": 0}}, {"product_id": 1, "categorie": 1, "variants": 1}):
        for v in prod["variants"]:
            if v["stock"] >= 2:
                skus_disponibles.append({
                    "product_id": prod["product_id"],
                    "sku":        v["sku"],
                    "prix":       v["prix"],
                    "categorie":  prod["categorie"],
                })
    return skus_disponibles


# ─────────────────────────────────────────
# PIPELINE DE SYNCHRONISATION — ACHAT
# ─────────────────────────────────────────

class PurchasePipeline:
    """
    Simule un achat et synchronise les 3 bases en parallèle :
    - MongoDB  : décrémente le stock de la variante (SKU)
    - Redis    : publie un événement + met à jour top_sales
    - Neo4j    : crée la relation [:PURCHASED]
    """

    def __init__(self, db, neo4j_driver, redis_client):
        self.db    = db
        self.neo4j = neo4j_driver
        self.redis = redis_client

    async def acheter(self, customer_id, product_id, sku, quantite, prix, categorie):
        tx_id        = f"TX-SYNC-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
        total        = round(prix * quantite, 2)

        logger.info(f"Achat {tx_id} — {customer_id} achète {sku} x{quantite}")

        # Les 3 opérations lancées en parallèle
        resultats = await asyncio.gather(
            self._mongo_decrémenter_stock(product_id, sku, quantite, tx_id, customer_id, prix, total, categorie),
            self._redis_publier_evenement(tx_id, customer_id, product_id, sku, quantite, total, categorie),
            self._neo4j_creer_relation(customer_id, product_id, tx_id, quantite, prix, total, categorie),
            return_exceptions=True
        )

        mongo_ok = not isinstance(resultats[0], Exception)
        redis_ok = not isinstance(resultats[1], Exception)
        neo4j_ok = not isinstance(resultats[2], Exception)

        for i, (nom, ok, res) in enumerate([("MongoDB", mongo_ok, resultats[0]), ("Redis", redis_ok, resultats[1]), ("Neo4j", neo4j_ok, resultats[2])]):
            if not ok:
                logger.error(f"  {nom} erreur : {res}")

        statut = "succes" if all([mongo_ok, redis_ok, neo4j_ok]) else "partiel"
        logger.info(f"  → {tx_id} | {statut} | MongoDB:{mongo_ok} Redis:{redis_ok} Neo4j:{neo4j_ok} | Total:{total} XOF")
        return statut

    async def _mongo_decrémenter_stock(self, product_id, sku, quantite, tx_id, customer_id, prix, total, categorie):
        """Décrémente le stock de la variante et enregistre la transaction."""
        col_cat = self.db["catalogue"]
        col_tx  = self.db["transactions"]

        result = await col_cat.update_one(
            {
                "product_id":     product_id,
                "variants.sku":   sku,
                "variants.stock": {"$gte": quantite},
            },
            {
                "$inc": {"variants.$.stock": -quantite, "stock_total": -quantite},
                "$set": {"mis_a_jour": datetime.now().isoformat()},
            }
        )

        if result.matched_count == 0:
            raise ValueError(f"Stock insuffisant ou SKU introuvable : {sku}")

        await col_tx.insert_one({
            "transaction_id":   tx_id,
            "customer_id":      customer_id,
            "product_id":       product_id,
            "sku":              sku,
            "quantity":         quantite,
            "unit_price":       prix,
            "total_amount":     total,
            "product_category": categorie,
            "transaction_date": datetime.now().isoformat(),
            "source":           "sync_pipeline",
        })
        logger.info(f"  MongoDB ✓ stock {sku} décrémenté de {quantite}")

    async def _redis_publier_evenement(self, tx_id, customer_id, product_id, sku, quantite, total, categorie):
        """Publie l'événement d'achat et met à jour les classements."""
        evenement = {
            "type":           "achat",
            "transaction_id": tx_id,
            "customer_id":    customer_id,
            "product_id":     product_id,
            "sku":            sku,
            "quantite":       quantite,
            "total":          total,
            "categorie":      categorie,
            "timestamp":      datetime.now().isoformat(),
        }
        pipe = self.redis.pipeline(transaction=False)
        pipe.publish("achats", json.dumps(evenement))          # Pub/Sub temps réel
        pipe.zincrby("top_sales", total, product_id)           # Classement CA
        pipe.hincrby("ventes_par_categorie", categorie, quantite)  # Compteur
        pipe.lpush("journal_achats", json.dumps(evenement))    # Historique
        pipe.ltrim("journal_achats", 0, 999)
        await pipe.execute()
        logger.info(f"  Redis ✓ événement publié + top_sales mis à jour")

    async def _neo4j_creer_relation(self, customer_id, product_id, tx_id, quantite, prix, total, categorie):
        """Crée la relation [:PURCHASED] entre le client et le produit."""
        cypher = """
        MERGE (c:Customer {id: $customer_id})
        MERGE (p:Product  {id: $product_id})
          ON CREATE SET p.category = $categorie
        CREATE (c)-[:PURCHASED {
            transaction_id: $tx_id,
            quantity:       $quantite,
            unit_price:     $prix,
            total_amount:   $total,
            date:           $date,
            category:       $categorie
        }]->(p)
        """
        async with self.neo4j.session() as session:
            await session.run(cypher,
                customer_id=customer_id,
                product_id=product_id,
                tx_id=tx_id,
                quantite=quantite,
                prix=prix,
                total=total,
                date=datetime.now().isoformat(),
                categorie=categorie,
            )
        logger.info(f"  Neo4j ✓ relation [:PURCHASED] créée")


# ─────────────────────────────────────────
# POINT D'ENTRÉE
# ─────────────────────────────────────────

async def main():
    logger.info("══════════ DÉMARRAGE SCHEMA + SYNC PIPELINE ══════════")

    # Connexions
    mongo  = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db     = mongo["ecommerce"]
    neo4j  = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASS))
    redis  = aioredis.from_url(f"redis://{REDIS_HOST}:{REDIS_PORT}", decode_responses=True)

    try:
        # Étape 1 : Schéma MongoDB enrichi
        logger.info("── Étape 1 : Création du schéma MongoDB avec variantes ──")
        skus_dispo = await setup_schema(db)
        logger.info(f"SKUs disponibles pour simulation : {len(skus_dispo)}")

        # Étape 2 : Simulation d'achats avec de vrais SKUs
        logger.info("── Étape 2 : Simulation de 5 achats synchronisés ──")
        pipeline = PurchasePipeline(db, neo4j, redis)

        clients = ["CUST-32810", "CUST-50685", "CUST-56090", "CUST-18968", "CUST-93695"]

        for i in range(5):
            item   = random.choice(skus_dispo)
            client = clients[i]
            await pipeline.acheter(
                customer_id=client,
                product_id=item["product_id"],
                sku=item["sku"],
                quantite=random.randint(1, 3),
                prix=item["prix"],
                categorie=item["categorie"],
            )
            await asyncio.sleep(0.1)

    finally:
        mongo.close()
        await neo4j.close()
        await redis.aclose()

    logger.info("══════════ PIPELINE TERMINÉ ══════════")


if __name__ == "__main__":
    asyncio.run(main())