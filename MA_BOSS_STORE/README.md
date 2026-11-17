# MA.BOSS STORE — Flask

## Contenu
- Boutique existante conservée dans `templates/index.html` et `static/app.js`.
- Catalogue administrable (CRUD) avec upload Cloudinary.
- SQLite en développement, PostgreSQL possible en production.
- Paiement CinetPay XOF : création de facture et confirmation serveur-à-serveur.

## Installation Ubuntu
```bash
cd MA_BOSS_STORE_FLASK
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
Configurez `.env` avant de démarrer. Pour créer le hash du mot de passe administrateur :
```bash
python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('VotreMotDePasseFort'))"
```
Copiez le hash obtenu dans `ADMIN_PASSWORD_HASH`. Changez `FLASK_SECRET_KEY` avec une longue valeur aléatoire.

## Lancement local
```bash
flask --app app run --debug
```
Boutique : http://127.0.0.1:5000/
Admin : http://127.0.0.1:5000/admin-login

## Cloudinary
Créez un compte Cloudinary et renseignez les trois variables `CLOUDINARY_*`. Les images sont uploadées côté serveur avec le SDK Python. Ne publiez jamais `CLOUDINARY_API_SECRET`.

## CinetPay
Renseignez `CINETPAY_API_KEY`, `CINETPAY_SITE_ID` et `BASE_URL` (URL HTTPS publique). Dans le tableau de bord CinetPay, configurez l'URL de notification `https://votre-domaine.com/api/webhook/cinetpay`. Testez en environnement de test avant toute mise en production et vérifiez que les moyens de paiement souhaités sont activés pour votre compte et le Burkina Faso. Le backend recalcule le montant à partir des prix en base, puis vérifie le statut, le montant et la devise auprès de CinetPay avant de marquer une commande `PAID`.

## Sécurité et déploiement
- Ne commitez jamais `.env`, les clés API ou la base de données.
- HTTPS obligatoire en production (`COOKIE_SECURE=true`).
- Désactivez le mode debug en production. Utilisez Gunicorn, par exemple `gunicorn -w 2 -b 0.0.0.0:8000 app:app`.
- Configurez sauvegardes PostgreSQL et politique de conservation des commandes.
- Le paiement reste désactivé tant que les identifiants et une URL HTTPS ne sont pas configurés.

## Notes
Le formulaire de checkout actuel a été adapté pour lancer le paiement en ligne. Le bouton WhatsApp de commande directe depuis une fiche produit reste disponible. Les anciens produits codés en dur dans `app.js` servent de solution de secours d'affichage tant que la base est vide ; ajoutez les produits depuis l'admin pour alimenter le catalogue serveur.
