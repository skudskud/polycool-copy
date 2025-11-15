#!/usr/bin/env python3
"""
Script de rollback automatique du streamer
Commente le streamer dans main.py et garde une backup
"""

import os
import shutil
from pathlib import Path

def rollback_streamer():
    """Rollback automatique du streamer"""

    print("🛡️ ROLLBACK STREAMER - DÉBUT")
    print("="*50)

    # Chemin vers main.py
    main_file = Path(__file__).parent.parent / "src" / "main.py"
    backup_file = main_file.with_suffix('.py.backup')

    try:
        # Lire le contenu actuel
        with open(main_file, 'r') as f:
            content = f.read()

        # Créer backup si pas déjà fait
        if not backup_file.exists():
            shutil.copy2(main_file, backup_file)
            print(f"✅ Backup créé: {backup_file}")

        # Chercher et commenter les lignes streamer
        lines = content.split('\n')
        modified = False

        for i, line in enumerate(lines):
            if 'if settings.STREAMER_ENABLED:' in line and not line.strip().startswith('#'):
                # Commenter le bloc streamer (4 lignes)
                for j in range(4):  # streamer + 3 lignes suivantes
                    if i+j < len(lines) and not lines[i+j].strip().startswith('#'):
                        lines[i+j] = f"# {lines[i+j]}"
                        modified = True

        if modified:
            # Écrire le fichier modifié
            with open(main_file, 'w') as f:
                f.write('\n'.join(lines))

            print("✅ Streamer commenté dans main.py")
            print("✅ Rollback terminé avec succès")
            print("\n📋 PROCHAINES ÉTAPES:")
            print("   1. git add . && git commit -m 'rollback streamer'")
            print("   2. railway deploy")
            print("   3. Vérifier que le système fonctionne avec API normale")

        else:
            print("⚠️ Aucune modification nécessaire (streamer déjà commenté?)")

    except Exception as e:
        print(f"❌ ERREUR lors du rollback: {e}")

        # Restaurer backup si possible
        if backup_file.exists():
            try:
                shutil.copy2(backup_file, main_file)
                print(f"✅ Backup restauré depuis {backup_file}")
            except Exception as restore_error:
                print(f"❌ Impossible de restaurer backup: {restore_error}")

    print("="*50)
    print("🛡️ ROLLBACK STREAMER - FIN")


if __name__ == "__main__":
    rollback_streamer()
