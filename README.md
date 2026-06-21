# Projet NoSQL E-Commerce
> Module Bases de données NoSQL — Master 1 — AFI-UE Dakar

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Docker Network                          │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                │
│  │  mongo1  │←→│  mongo2  │←→│  mongo3  │  Replica Set rs0 │
│  │ PRIMARY  │   │SECONDARY │   │SECONDARY │                 │
│  └──────────┘   └──────────┘   └──────────┘                │
│                                                              │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐                │
│  │  Neo4j   │   │  Redis   │   │ FastAPI  │                │
│  │  :7687   │   │  :6379   │   │  :8000   │                │
│  └──────────┘   └──────────┘   └──────────┘                │
└─────────────────────────────────────────────────────────────┘

         ┌──────────────────────┐
         │   React + MUI :3000  │
         └──────────────────────┘
```

## 📁 Structure du projet

```
ecommerce-nosql/
├── docker/
│   ├── docker-compose.yml          ← Infrastructure (MongoDB RS, Neo4j, Redis)
│   └── init-replicaset.sh          ← Initialisation automatique du Replica Set
├── ecommerce-back/
│   ├── data/
│   │   └── ecommerce_raw_transactions_dirty.csv  ← Données brutes (101 500 lignes)
│   ├── scripts/
│   │   ├── clean_and_inject.py     ← Pipeline nettoyage + injection bulk
│   │   └── schema_and_sync.py      ← Schéma enrichi + pipeline d'achat asynchrone
│   └── api/
│       └── main.py                 ← API REST FastAPI
└── ecommerce-front/                ← Interface React + Material UI
    └── src/
        ├── pages/
        │   ├── Dashboard.js        ← Analytics & KPIs
        │   ├── Catalogue.js        ← Recherche textuelle avec facettes
        │   └── Recommandations.js  ← Moteur Neo4j
        └── api/
            └── client.js           ← Appels API centralisés
```

## 🚀 Démarrage rapide

### Prérequis
- Docker Desktop ≥ 24
- Python 3.12+
- Node.js 22+

### 1. Lancer l'infrastructure

```bash
cd docker
docker compose up -d
```

Initialise le Replica Set manuellement si nécessaire :
```bash
docker exec -it mongo1 mongosh --eval "rs.initiate({_id:'rs0', members:[{_id:0,host:'mongo1:27017'},{_id:1,host:'mongo2:27017'},{_id:2,host:'mongo3:27017'}]})"
```

### 2. Lancer le pipeline de données

```bash
cd ecommerce-back/scripts
pip install pandas pymongo neo4j redis motor
python clean_and_inject.py      # Nettoyage + injection bulk
python schema_and_sync.py       # Schéma enrichi + simulation achats
```

### 3. Lancer l'API

```bash
cd ecommerce-back/api
pip install fastapi uvicorn pymongo neo4j redis
python -m uvicorn main:app --reload --port 8000
```

API disponible sur `http://localhost:8000/docs`

### 4. Lancer le front

```bash
cd ecommerce-front
npm install --legacy-peer-deps
npm start
```

Front disponible sur `http://localhost:3000`

---

## 📊 Étape 1 — Data Quality

Le fichier brut `ecommerce_raw_transactions_dirty.csv` contient **101 500 lignes** avec plusieurs anomalies :

| Anomalie | Traitement | Volume |
|----------|-----------|--------|
| Doublons stricts | Supprimés | 1 500 |
| Dates invalides (`2026/03/21`, `2025-00-99`) | Rejetées + journalisées | 1 013 |
| Prix corrompus (`112.09 CFA`, `-99.99`) | Corrigés ou rejetés | 1 009 |
| Quantités négatives/nulles | Rejetées + journalisées | 2 027 |
| Transactions anonymes | Conservées MongoDB, exclues Neo4j | 2 020 |
| **Transactions propres injectées** | | **95 951** |

Journal de rejet : `ecommerce-back/scripts/logs/rejected_rows.json`

---

## 🗄️ Étape 2 — Modélisation & Injection

### MongoDB — Schéma enrichi avec variantes

```json
{
  "product_id": "PROD-001",
  "nom": "T-Shirt Premium",
  "categorie": "Mode",
  "prix_base": 29.99,
  "variants": [
    { "sku": "PROD-001-S-NOI", "taille": "S", "couleur": "Noir", "stock": 50, "prix": 29.99 },
    { "sku": "PROD-001-M-BLA", "taille": "M", "couleur": "Blanc", "stock": 80, "prix": 29.99 }
  ],
  "stock_total": 130
}
```

Injection en masse via **Bulk Operations** (lots de 1000).

### Neo4j — Graphe des interactions

```cypher
(Customer)-[:PURCHASED]->(Product)
```

- **1 976** clients
- **392** produits
- **93 931** relations PURCHASED

Injection via **UNWIND** Cypher (batch).

### Redis — Cache & Sessions

- Sessions utilisateur avec TTL (1h)
- Sorted Set `top_sales` (classement temps réel)
- Compteurs par catégorie

---

## 🔄 Pipeline de synchronisation asynchrone

`schema_and_sync.py` simule un achat en lançant **3 opérations en parallèle** via `asyncio.gather` :

```
Achat → asyncio.gather(
    MongoDB  : décrémente stock variante SKU,
    Redis    : publie événement Pub/Sub + met à jour top_sales,
    Neo4j    : crée relation [:PURCHASED]
)
```

---

## 🌐 API REST — Endpoints

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/health` | État des 3 bases |
| `GET` | `/products/top` | Top produits par CA (MongoDB) |
| `GET` | `/analytics/revenue-by-category` | CA global par catégorie |
| `GET` | `/analytics/revenue-last-30-days` | CA des 30 derniers jours |
| `GET` | `/catalogue/search?q=...` | Recherche textuelle avec facettes |
| `GET` | `/recommendations/{id}?depth=2\|3` | Recommandations Neo4j collaboratif |
| `GET` | `/sales/realtime-top` | Top ventes Redis temps réel |
| `POST` | `/sessions` | Créer une session (Redis TTL) |
| `GET` | `/sessions/{id}` | Lire une session |

**Rate Limiting** : 60 requêtes/minute/IP via Redis sliding window.

---

## 🧠 Algorithme de recommandation Neo4j

### Profondeur 2
```cypher
Client → achète → Produit ← achète ← Client similaire → achète → Produit recommandé
```

### Profondeur 3
```cypher
Client → L1 → Produit → L2 → Produit recommandé (cercle élargi)
```

---

## 🐳 Haute Disponibilité — Replica Set MongoDB

Le Replica Set `rs0` tolère la panne d'un nœud :

```bash
# Simuler une panne du PRIMARY
docker stop mongo1

# Vérifier l'élection automatique
docker exec -it mongo2 mongosh --eval "rs.status().members.forEach(m => print(m.name, m.stateStr))"

# Remettre en ligne — resynchronisation automatique
docker start mongo1
```

**Redis AOF** activé : `--appendonly yes` — chaque écriture journalisée sur disque.

---

## 🖥️ Interface React

- **Dashboard** : KPIs, CA par catégorie (Bar + Pie charts), top ventes Redis
- **Catalogue** : Recherche textuelle avec facettes catégories + tranches de prix
- **Recommandations** : Profil client + recommandations Neo4j depth 2/3

---

## 👩‍💻 Auteur

**Benyamine IDISSA & Emmanuelle D'Edith NGANGA MOULEBE**  
Master 1 — AFI-UE Dakar  
