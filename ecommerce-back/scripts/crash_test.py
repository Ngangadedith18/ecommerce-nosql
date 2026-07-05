# -*- coding: utf-8 -*-
"""
Script de Crash-Test — Démonstration Haute Disponibilité
=========================================================
Ce script écrit en continu dans MongoDB pendant la démo.
Le prof coupe un nœud → le script continue sans interruption.
"""

import time
import random
from datetime import datetime
from pymongo import MongoClient

MONGO_URI = "mongodb://localhost:27017/?directConnection=true&serverSelectionTimeoutMS=5000"

client = MongoClient(MONGO_URI)
db     = client["ecommerce"]
col    = db["crash_test"]

print("══════════ CRASH TEST DÉMARRÉ ══════════")
print("Écritures en continu dans MongoDB...")
print("→ Coupez un nœud avec : docker stop mongo1")
print("→ Arrêtez ce script avec : Ctrl+C")
print("════════════════════════════════════════\n")

compteur = 0
erreurs  = 0

while True:
    try:
        doc = {
            "test_id":    f"CRASH-{compteur:06d}",
            "timestamp":  datetime.now().isoformat(),
            "valeur":     random.randint(1, 1000),
            "statut":     "ok",
        }
        col.insert_one(doc)
        compteur += 1
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Écriture #{compteur} réussie")
        time.sleep(1)

    except Exception as e:
        erreurs += 1
        print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️  Erreur #{erreurs} : {e}")
        print("  → Tentative de reconnexion...")
        time.sleep(2)