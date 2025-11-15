#!/usr/bin/env python3
"""
DIAGNOSTIC ET RÉPARATION REDIS
=============================

Script pour diagnostiquer et réparer les problèmes Redis/circuit breaker
"""

import os
import sys

def check_redis_server():
    """Vérifier que Redis tourne"""
    print("🔍 VÉRIFICATION REDIS SERVER")
    print("-" * 40)
    
    # Test avec redis-cli si disponible
    import subprocess
    try:
        result = subprocess.run(['redis-cli', 'ping'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and 'PONG' in result.stdout:
            print("✅ Redis server: RUNNING")
            return True
        else:
            print("❌ Redis server: NOT RESPONDING")
            return False
    except FileNotFoundError:
        print("⚠️ redis-cli not found, testing with Python client...")
        return None
    except Exception as e:
        print(f"❌ Error checking Redis server: {e}")
        return False

def check_redis_connection():
    """Tester la connexion Redis avec Python"""
    print("\n🔍 TEST CONNEXION PYTHON")
    print("-" * 40)
    
    try:
        import redis
        redis_url = os.getenv('REDIS_URL')
        
        if not redis_url:
            print("❌ REDIS_URL not set in environment")
            return False
            
        print(f"Redis URL: {redis_url.replace(redis_url.split('://')[1].split('@')[0], '***:***@')}")
        
        client = redis.from_url(redis_url, socket_timeout=5, socket_connect_timeout=5)
        pong = client.ping()
        
        if pong:
            print("✅ Python connection: SUCCESS")
            info = client.info('server')
            redis_version = info.get('redis_version', 'unknown')
            print(f"✅ Redis version: {redis_version}")
            return True
        else:
            print("❌ Python connection: FAILED")
            return False
            
    except Exception as e:
        print(f"❌ Python connection error: {e}")
        return False

def check_circuit_breaker():
    """Vérifier l'état du circuit breaker"""
    print("\n🔍 ÉTAT CIRCUIT BREAKER")
    print("-" * 40)
    
    try:
        from core.services.redis_circuit_breaker import get_circuit_breaker
        
        cb = get_circuit_breaker()
        health = cb.get_health_status()
        
        print(f"État: {health['state']}")
        print(f"Échecs: {health['failure_count']}")
        print(f"Dernier échec: {health['last_failure']}")
        print(f"Prochaine tentative: {health['next_attempt']}")
        print(f"Redis accessible: {health['is_healthy']}")
        
        return health
        
    except Exception as e:
        print(f"❌ Erreur circuit breaker: {e}")
        return None

def reset_circuit_breaker():
    """Reset le circuit breaker"""
    print("\n🔄 RESET CIRCUIT BREAKER")
    print("-" * 40)
    
    try:
        from core.services.redis_circuit_breaker import get_circuit_breaker
        
        cb = get_circuit_breaker()
        
        # Reset en simulant un succès
        cb.record_success()
        cb._failure_count = 0
        cb._state = cb.CircuitState.CLOSED
        cb._last_failure_time = None
        cb._next_attempt_time = None
        
        health = cb.get_health_status()
        print(f"✅ Circuit breaker reset: {health['state']}")
        print(f"✅ Échecs: {health['failure_count']}")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur reset: {e}")
        return False

def test_full_integration():
    """Test complet après réparation"""
    print("\n🧪 TEST INTÉGRATION COMPLÈTE")
    print("-" * 40)
    
    try:
        from core.services.redis_price_cache import RedisPriceCache
        
        cache = RedisPriceCache()
        
        if not cache.enabled:
            print("❌ Cache désactivé")
            return False
            
        print(f"✅ Cache activé: {cache.enabled}")
        
        # Test simple
        success = cache.cache_token_price('diagnostic_test', 1.0, ttl=30)
        print(f"✅ Écriture test: {success}")
        
        price = cache.get_token_price('diagnostic_test')
        print(f"✅ Lecture test: {price}")
        
        # Test circuit breaker
        cb_stats = cache.get_cache_stats().get('circuit_breaker', {})
        print(f"✅ Circuit state: {cb_stats.get('state', 'unknown')}")
        
        # Test locks
        lock_ok = cache.acquire_lock('diagnostic_lock', 5)
        if lock_ok:
            cache.release_lock('diagnostic_lock')
            print("✅ Locks: OK")
        else:
            print("⚠️ Locks: Non acquis")
        
        # Test mémoire
        mem_stats = cache.get_memory_stats()
        print(f"✅ Mémoire: {mem_stats['status']} ({mem_stats['memory']['usage_percent']}%)")
        
        return True
        
    except Exception as e:
        print(f"❌ Erreur intégration: {e}")
        return False

def main():
    print("🔧 DIAGNOSTIC ET RÉPARATION REDIS")
    print("=" * 50)
    
    # Étape 1: Vérifier Redis server
    redis_running = check_redis_server()
    
    # Étape 2: Tester connexion Python
    redis_connected = check_redis_connection()
    
    # Étape 3: Vérifier circuit breaker
    cb_health = check_circuit_breaker()
    
    print("\n" + "=" * 50)
    print("📋 RÉSULTATS DIAGNOSTIC")
    print("=" * 50)
    
    issues = []
    
    if redis_running is False:
        issues.append("Redis server ne tourne pas")
    elif redis_running is None:
        print("⚠️ Impossible de vérifier Redis server (redis-cli manquant)")
    
    if not redis_connected:
        issues.append("Connexion Python Redis échoue")
    
    if cb_health and cb_health['state'] == 'open':
        issues.append(f"Circuit breaker ouvert ({cb_health['failure_count']} échecs)")
    
    if issues:
        print("❌ PROBLÈMES DÉTECTÉS:")
        for issue in issues:
            print(f"  - {issue}")
        
        print("\n🛠️ RÉPARATIONS:")
        
        if "Redis server ne tourne pas" in str(issues):
            print("  1. Lancer Redis: redis-server")
        
        if "Connexion Python" in str(issues):
            print("  2. Vérifier REDIS_URL dans Railway")
        
        if "Circuit breaker ouvert" in str(issues):
            print("  3. Reset du circuit breaker...")
            if reset_circuit_breaker():
                print("     ✅ Circuit breaker reset réussi")
            else:
                print("     ❌ Échec reset circuit breaker")
        
        print("\n🔄 RETESTER APRÈS RÉPARATIONS...")
        test_full_integration()
        
    else:
        print("✅ AUCUN PROBLÈME DÉTECTÉ")
        test_full_integration()
    
    print("\n" + "=" * 50)
    print("💡 COMMANDES SUIVANTES:")
    print("  python test_resilience_complete.py  # Re-tester tout")
    print("  python redis_diagnostic.py          # Re-diagnostic")
    print("=" * 50)

if __name__ == "__main__":
    main()
