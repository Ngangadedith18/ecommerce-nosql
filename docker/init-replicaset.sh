#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# Initialisation du Replica Set MongoDB (rs0)
# Exécuté une seule fois par le service mongo-init
# ─────────────────────────────────────────────────────────────────

set -e

echo "⏳  Attente de mongo1..."
until mongosh --host mongo1:27017 -u admin -p secret --authenticationDatabase admin \
      --eval "db.adminCommand('ping')" --quiet; do
  sleep 2
done

echo "⏳  Attente de mongo2..."
until mongosh --host mongo2:27017 -u admin -p secret --authenticationDatabase admin \
      --eval "db.adminCommand('ping')" --quiet; do
  sleep 2
done

echo "⏳  Attente de mongo3..."
until mongosh --host mongo3:27017 -u admin -p secret --authenticationDatabase admin \
      --eval "db.adminCommand('ping')" --quiet; do
  sleep 2
done

# Vérifie si le Replica Set est déjà initialisé
RS_STATUS=$(mongosh --host mongo1:27017 -u admin -p secret --authenticationDatabase admin \
  --eval "try { rs.status().ok } catch(e) { 0 }" --quiet 2>/dev/null || echo "0")

if [ "$RS_STATUS" = "1" ]; then
  echo "✅  Replica Set déjà initialisé — rien à faire."
  exit 0
fi

echo "🔧  Initialisation du Replica Set rs0..."
mongosh --host mongo1:27017 -u admin -p secret --authenticationDatabase admin --eval '
rs.initiate({
  _id: "rs0",
  members: [
    { _id: 0, host: "mongo1:27017", priority: 2 },
    { _id: 1, host: "mongo2:27017", priority: 1 },
    { _id: 2, host: "mongo3:27017", priority: 1 }
  ]
});
'

# Attend l'élection du PRIMARY
echo "⏳  Attente de l'élection du PRIMARY..."
until mongosh --host mongo1:27017 -u admin -p secret --authenticationDatabase admin \
      --eval "rs.isMaster().ismaster" --quiet 2>/dev/null | grep -q "true"; do
  sleep 3
done

echo "✅  Replica Set rs0 opérationnel — mongo1 est PRIMARY."
echo ""
echo "📊  État du Replica Set :"
mongosh --host mongo1:27017 -u admin -p secret --authenticationDatabase admin \
  --eval "rs.status().members.forEach(m => print(m.name, '-', m.stateStr))" --quiet