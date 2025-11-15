#!/bin/bash
# Script pour exécuter les migrations du système de fees
# Usage: ./execute_migrations.sh

echo "🚀 Exécution des migrations du système de fees"
echo ""

# Vérifier que DATABASE_URL est défini
if [ -z "$DATABASE_URL" ]; then
    echo "❌ Erreur: DATABASE_URL n'est pas défini"
    echo ""
    echo "Définissez-le avec:"
    echo "  export DATABASE_URL='postgresql://...'"
    echo ""
    echo "Ou récupérez-le depuis Railway:"
    echo "  1. Allez sur railway.app"
    echo "  2. Sélectionnez votre projet"
    echo "  3. Cliquez sur PostgreSQL"
    echo "  4. Variables → DATABASE_URL"
    exit 1
fi

echo "📊 Connexion à la base de données..."
echo ""

# Migration 1
echo "📝 [1/3] Création de la table referrals..."
psql "$DATABASE_URL" -f 001_create_referrals_table.sql
if [ $? -eq 0 ]; then
    echo "   ✅ Succès"
else
    echo "   ❌ Échec"
    exit 1
fi
echo ""

# Migration 2
echo "📝 [2/3] Création de la table fees..."
psql "$DATABASE_URL" -f 002_create_fees_table.sql
if [ $? -eq 0 ]; then
    echo "   ✅ Succès"
else
    echo "   ❌ Échec"
    exit 1
fi
echo ""

# Migration 3
echo "📝 [3/3] Création de la table referral_commissions..."
psql "$DATABASE_URL" -f 003_create_referral_commissions_table.sql
if [ $? -eq 0 ]; then
    echo "   ✅ Succès"
else
    echo "   ❌ Échec"
    exit 1
fi
echo ""

echo "✅ Toutes les migrations ont été exécutées avec succès!"
echo ""
echo "🔍 Vérification des tables créées..."
psql "$DATABASE_URL" -c "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' AND table_name IN ('referrals', 'fees', 'referral_commissions') ORDER BY table_name;"
echo ""
echo "🎉 Migration complète! Le système de fees est prêt."
