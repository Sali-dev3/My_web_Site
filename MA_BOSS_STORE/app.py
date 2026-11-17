import os, uuid, hmac, hashlib, secrets, json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps

import requests
import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect, generate_csrf
from werkzeug.security import check_password_hash
from werkzeug.utils import secure_filename

load_dotenv()
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv('FLASK_SECRET_KEY', 'change-this-development-secret'),
    SQLALCHEMY_DATABASE_URI=os.getenv('DATABASE_URL', 'sqlite:///maboss.db').replace('postgres://','postgresql://'),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=5 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.getenv('COOKIE_SECURE','false').lower() == 'true',
)
db=SQLAlchemy(app)
csrf=CSRFProtect(app)

SHIPPING_CITIES = {
    'Bobo-Dioulasso', 'Koudougou', 'Banfora', 'Ouahigouya', 'Kaya',
    "Fada N'Gourma", 'Dédougou', 'Tenkodogo', 'Gaoua', 'Dori', 'Manga',
    'Ziniaré', 'Koupéla', 'Houndé', 'Léo', 'Pô',
}

cloudinary.config(cloud_name=os.getenv('CLOUDINARY_CLOUD_NAME'), api_key=os.getenv('CLOUDINARY_API_KEY'), api_secret=os.getenv('CLOUDINARY_API_SECRET'), secure=True)

class Product(db.Model):
    id=db.Column(db.Integer, primary_key=True)
    name=db.Column(db.String(140), nullable=False)
    price=db.Column(db.Integer, nullable=False)
    description=db.Column(db.Text, default='')
    category=db.Column(db.String(60), nullable=False, default='parfum')
    image_url=db.Column(db.String(600), default='')
    cloudinary_public_id=db.Column(db.String(255))
    is_popular=db.Column(db.Boolean, default=False)
    is_new=db.Column(db.Boolean, default=False)
    created_at=db.Column(db.DateTime, default=datetime.utcnow)
    def public(self):
        return {'id':self.id,'name':self.name,'price':self.price,'description':self.description,'category':self.category,'image':self.image_url,'image_url':self.image_url,'is_popular':self.is_popular,'is_new':self.is_new,'notes':{'top':'','heart':'','base':''}}

class Order(db.Model):
    id=db.Column(db.Integer, primary_key=True)
    reference=db.Column(db.String(40), unique=True, nullable=False)
    customer_name=db.Column(db.String(140), nullable=False)
    phone=db.Column(db.String(40), nullable=False)
    address=db.Column(db.String(300), nullable=False)
    delivery=db.Column(db.String(120), nullable=False)
    items_json=db.Column(db.Text, nullable=False)
    amount=db.Column(db.Integer, nullable=False)
    status=db.Column(db.String(30), default='PENDING')
    payment_url=db.Column(db.String(700))
    provider_transaction_id=db.Column(db.String(100))
    created_at=db.Column(db.DateTime, default=datetime.utcnow)


def admin_required(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        if not session.get('is_admin'):
            return jsonify({'error':'Authentification administrateur requise.'}),401
        return fn(*args,**kwargs)
    return wrapped

def admin_page_required(fn):
    @wraps(fn)
    def wrapped(*args,**kwargs):
        if not session.get('is_admin'): return redirect(url_for('admin_login_page'))
        return fn(*args,**kwargs)
    return wrapped

def clean_product_payload(data):
    name=str(data.get('name','')).strip()
    category=str(data.get('category','')).strip().lower()
    description=str(data.get('description','')).strip()
    try: price=int(data.get('price'))
    except (ValueError,TypeError): raise ValueError('Le prix doit être un nombre entier en FCFA.')
    if not name or len(name)>140: raise ValueError('Nom du produit obligatoire (140 caractères maximum).')
    if price < 1 or price > 100000000: raise ValueError('Prix invalide.')
    if category not in ('parfum','vetement','accessoire','femme','homme','mixte'): raise ValueError('Catégorie invalide.')
    return name,price,description,category

def upload_product_image(file):
    if not file or not file.filename: return None
    allowed={'jpg','jpeg','png','webp'}
    ext=file.filename.rsplit('.',1)[-1].lower() if '.' in file.filename else ''
    if ext not in allowed: raise ValueError('Format image accepté : JPG, JPEG, PNG ou WEBP.')
    filename=secure_filename(f'{uuid.uuid4().hex}.{ext}')
    upload_dir=os.path.join(app.static_folder,'uploads','products')
    os.makedirs(upload_dir,exist_ok=True)
    file.save(os.path.join(upload_dir,filename))
    return f'/static/uploads/products/{filename}', None

def delete_local_product_image(image_url):
    prefix='/static/uploads/products/'
    if not image_url or not image_url.startswith(prefix): return
    filename=os.path.basename(image_url)
    if filename != image_url[len(prefix):]: return
    image_path=os.path.join(app.static_folder,'uploads','products',filename)
    try: os.remove(image_path)
    except FileNotFoundError: pass

@app.context_processor
def inject_csrf(): return {'csrf_token':generate_csrf}

@app.get('/')
def home(): return render_template('index.html')

@app.get('/admin-login')
def admin_login_page(): return render_template('admin_login.html')

@app.post('/api/admin/login')
def admin_login():
    data=request.get_json(silent=True) or {}
    username=os.getenv('ADMIN_USERNAME','admin')
    password_hash=os.getenv('ADMIN_PASSWORD_HASH','')
    # Require a configured password hash; never keep a production password in source code.
    if not password_hash or not secrets.compare_digest(str(data.get('username','')),username) or not check_password_hash(password_hash,str(data.get('password',''))):
        return jsonify({'error':'Identifiants incorrects.'}),401
    session.clear(); session['is_admin']=True
    return jsonify({'ok':True,'redirect':'/admin'})

@app.post('/api/admin/logout')
@admin_required
def admin_logout(): session.clear(); return jsonify({'ok':True})

@app.get('/admin')
@admin_page_required
def admin(): return render_template('admin.html')

@app.get('/api/products')
def list_products():
    products=Product.query.order_by(Product.created_at.desc()).all()
    return jsonify([p.public() for p in products])

@app.post('/api/admin/products')
@admin_required
def create_product():
    image_url=''
    try:
        name,price,description,category=clean_product_payload(request.form)
        image_file=request.files.get('photo') or request.files.get('image')
        if not image_file or not image_file.filename:
            raise ValueError('Veuillez sélectionner une image pour le produit.')
        uploaded=upload_product_image(image_file)
        image_url,public_id=uploaded
        p=Product(name=name,price=price,description=description,category=category,image_url=image_url,cloudinary_public_id=public_id,is_popular=request.form.get('is_popular')=='true',is_new=request.form.get('is_new')=='true')
        db.session.add(p); db.session.commit()
        return jsonify(p.public()),201
    except (ValueError,RuntimeError) as e: return jsonify({'error':str(e)}),400
    except Exception:
        db.session.rollback(); delete_local_product_image(image_url)
        app.logger.exception('create product failed')
        return jsonify({'error':'Erreur lors de la création du produit.'}),500

@app.put('/api/admin/products/<int:product_id>')
@admin_required
def update_product(product_id):
    p=db.session.get(Product,product_id)
    if not p: return jsonify({'error':'Produit introuvable.'}),404
    new_image_url=''
    try:
        name,price,description,category=clean_product_payload(request.form)
        p.name=name; p.price=price; p.description=description; p.category=category
        p.is_popular=request.form.get('is_popular')=='true'; p.is_new=request.form.get('is_new')=='true'
        image_file=request.files.get('photo') or request.files.get('image')
        if image_file and image_file.filename:
            uploaded=upload_product_image(image_file)
            new_url,new_public_id=uploaded
            new_image_url=new_url
            old_image_url=p.image_url
            old_public_id=p.cloudinary_public_id
            p.image_url=new_url; p.cloudinary_public_id=new_public_id
            db.session.commit()
            delete_local_product_image(old_image_url)
            if old_public_id:
                try: cloudinary.uploader.destroy(old_public_id)
                except Exception: app.logger.warning('Ancienne image Cloudinary non supprimée')
        else: db.session.commit()
        return jsonify(p.public())
    except (ValueError,RuntimeError) as e: db.session.rollback(); return jsonify({'error':str(e)}),400
    except Exception:
        db.session.rollback(); delete_local_product_image(new_image_url)
        app.logger.exception('update product failed')
        return jsonify({'error':'Erreur lors de la modification.'}),500

@app.delete('/api/admin/products/<int:product_id>')
@admin_required
def delete_product(product_id):
    p=db.session.get(Product,product_id)
    if not p: return jsonify({'error':'Produit introuvable.'}),404
    public_id=p.cloudinary_public_id
    image_url=p.image_url
    db.session.delete(p); db.session.commit()
    delete_local_product_image(image_url)
    if public_id:
        try: cloudinary.uploader.destroy(public_id)
        except Exception: app.logger.warning('Image Cloudinary non supprimée: %s',public_id)
    return jsonify({'ok':True})

@app.post('/api/payer')
@csrf.exempt
def initiate_payment():
    data=request.get_json(silent=True) or {}; customer=data.get('customer') or {}; items=data.get('items') or []
    required=['name','phone','address','delivery']
    if any(not str(customer.get(k,'')).strip() for k in required): return jsonify({'error':'Veuillez renseigner toutes vos coordonnées.'}),400
    delivery=str(customer['delivery']).strip()
    shipping_city=str(customer.get('city','')).strip()
    if delivery == 'Expédition autre ville' and shipping_city not in SHIPPING_CITIES:
        return jsonify({'error':'Veuillez sélectionner une ville de destination valide.'}),400
    if delivery != 'Expédition autre ville': shipping_city=''
    if not isinstance(items,list) or not items or len(items)>50: return jsonify({'error':'Panier invalide.'}),400
    order_lines=[]; amount=0
    try:
        for item in items:
            pid=int(item.get('product_id')); qty=int(item.get('quantity'))
            if qty<1 or qty>30: raise ValueError()
            product=db.session.get(Product,pid)
            if not product: return jsonify({'error':'Un produit du panier n’existe plus.'}),400
            amount += product.price*qty
            order_lines.append({'product_id':product.id,'name':product.name,'unit_price':product.price,'quantity':qty})
    except (ValueError,TypeError,AttributeError): return jsonify({'error':'Articles du panier invalides.'}),400
    if amount<100: return jsonify({'error':'Montant minimum invalide.'}),400
    api_key=os.getenv('CINETPAY_API_KEY'); site_id=os.getenv('CINETPAY_SITE_ID'); base_url=os.getenv('BASE_URL','').rstrip('/')
    if not api_key or not site_id or not base_url.startswith('https://'):
        return jsonify({'error':'Paiement non configuré : vérifiez les clés CinetPay et BASE_URL HTTPS dans .env.'}),503
    reference='MBS-'+uuid.uuid4().hex[:18].upper()
    order=Order(reference=reference,customer_name=str(customer['name'])[:140],phone=str(customer['phone'])[:40],address=str(customer['address'])[:300],delivery=(f'{delivery} - {shipping_city}' if shipping_city else delivery)[:120],items_json=json.dumps(order_lines,ensure_ascii=False),amount=amount)
    db.session.add(order); db.session.commit()
    payload={'apikey':api_key,'site_id':site_id,'transaction_id':reference,'amount':amount,'currency':'XOF','description':f'Commande MA.BOSS STORE {reference}','customer_name':order.customer_name,'customer_surname':order.customer_name,'customer_phone_number':order.phone,'customer_email':os.getenv('STORE_EMAIL','contact@maboss.store'),'customer_address':order.address,'customer_city':shipping_city or 'Ouagadougou','customer_country':'BF','customer_state':'Centre','customer_zip_code':'00000','notify_url':base_url+'/api/webhook/cinetpay','return_url':base_url+'/paiement/retour?reference='+reference,'channels':'ALL','metadata':reference,'lang':'FR'}
    try:
        response=requests.post('https://api-checkout.cinetpay.com/v2/payment',json=payload,timeout=20)
        result=response.json()
        if response.ok and str(result.get('code'))=='201' and result.get('data',{}).get('payment_url'):
            order.payment_url=result['data']['payment_url']; order.provider_transaction_id=result['data'].get('payment_token'); db.session.commit()
            return jsonify({'order_reference':reference,'payment_url':order.payment_url})
        app.logger.error('CinetPay init error: %s',result)
        order.status='INIT_FAILED'; db.session.commit()
        return jsonify({'error':'Le prestataire de paiement n’a pas accepté la demande. Vérifiez la configuration CinetPay.'}),502
    except requests.RequestException:
        app.logger.exception('CinetPay unavailable'); order.status='INIT_FAILED'; db.session.commit()
        return jsonify({'error':'Le service de paiement est momentanément indisponible.'}),502

@app.post('/api/webhook/cinetpay')
@csrf.exempt
def cinetpay_webhook():
    incoming=request.get_json(silent=True) or request.form.to_dict()
    reference=str(incoming.get('cpm_trans_id') or incoming.get('transaction_id') or incoming.get('merchant_transaction_id') or '')
    if not reference: return jsonify({'error':'Référence manquante'}),400
    order=Order.query.filter_by(reference=reference).first()
    if not order: return jsonify({'error':'Commande inconnue'}),404
    api_key=os.getenv('CINETPAY_API_KEY'); site_id=os.getenv('CINETPAY_SITE_ID')
    try:
        check=requests.post('https://api-checkout.cinetpay.com/v2/payment/check',json={'apikey':api_key,'site_id':site_id,'transaction_id':reference},timeout=15)
        result=check.json(); data=result.get('data') or {}
        # Only the server-to-server status check is trusted, never the webhook body.
        if check.ok and str(result.get('code'))=='00' and str(data.get('status','')).upper()=='ACCEPTED' and int(data.get('amount',data.get('cpm_amount',-1)))==order.amount and str(data.get('currency','XOF')).upper()=='XOF':
            order.status='PAID'
        elif check.ok and str(data.get('status','')).upper() in ('REFUSED','CANCELLED','FAILED'):
            order.status='FAILED'
        db.session.commit()
        return jsonify({'received':True}),200
    except Exception:
        db.session.rollback(); app.logger.exception('Webhook verification failed'); return jsonify({'error':'Vérification temporairement impossible'}),500

@app.get('/paiement/retour')
def payment_return():
    reference=request.args.get('reference','')
    order=Order.query.filter_by(reference=reference).first()
    return render_template('payment_return.html',order=order)

@app.get('/api/admin/orders')
@admin_required
def admin_orders():
    orders=Order.query.order_by(Order.created_at.desc()).limit(200).all()
    return jsonify([{'reference':o.reference,'customer':o.customer_name,'phone':o.phone,'amount':o.amount,'status':o.status,'created_at':o.created_at.isoformat(timespec='minutes')} for o in orders])

with app.app_context():
    db.create_all()
    # Preserve the eight products already present in the original static storefront.
    if Product.query.count() == 0:
        initial_products = [
            ('Nuit d’Ébène', 35000, 'femme', 'Une création d’exception façonnée avec élégance, mariant la délicatesse de la fleur de coton à une vanille noire envoûtante.', 'https://images.unsplash.com/photo-1592945403244-b3fbafd7f539?q=80&w=800', True, True),
            ('Santal du Sahel', 40000, 'homme', 'Un boisé noble au caractère intemporel, associant la chaleur du bois de santal à des notes épicées et cuirées.', 'https://images.unsplash.com/photo-1523293182086-7651a899d37f?q=80&w=800', True, False),
            ('Élixir d’Or', 50000, 'mixte', 'Un accord oriental majestueux où le précieux bois d’Oud s’unit à la douceur dorée du miel d’acacia.', 'https://images.unsplash.com/photo-1547887537-6158d64c35b3?q=80&w=800', True, True),
            ('Velours Floral', 30000, 'femme', 'Une douceur poudrée et féminine portée par un sillage frais de pivoines et de néroli de printemps.', 'https://images.unsplash.com/photo-1588405748880-12d1d2a59f75?q=80&w=800', True, False),
            ('Cuir Souverain', 45000, 'homme', 'Un parfum charismatique et masculin aux notes puissantes de cuir fumé et de vétiver profond.', 'https://images.unsplash.com/photo-1594035910387-fea47794261f?q=80&w=800', False, True),
            ('Rose de Soie', 32000, 'femme', 'Une fragrance romantique et raffinée offrant un sillage délicat de roses fraîches et de fruits rouges gourmands.', 'https://images.unsplash.com/photo-1563178406-4cdc2923acbc?q=80&w=800', False, False),
            ('Amber Royal', 48000, 'mixte', 'Une création envoûtante et chaleureuse bercée par des notes solaires d’ambre, de cannelle et de fève tonka.', 'https://images.unsplash.com/photo-1595425970377-c9703cf48b6d?q=80&w=800', False, True),
            ('Ombre Boisée', 38000, 'homme', 'Une essence ténébreuse et mystérieuse dominée par la fraîcheur du cyprès et l’intensité du bois de guiac.', 'https://images.unsplash.com/photo-1615397349754-cfa2066a298e?q=80&w=800', False, False),
        ]
        for name, price, category, description, image, popular, is_new in initial_products:
            db.session.add(Product(name=name, price=price, category=category, description=description, image_url=image, is_popular=popular, is_new=is_new))
        db.session.commit()

if __name__=='__main__': app.run(debug=os.getenv('FLASK_DEBUG','false').lower()=='true',host='127.0.0.1',port=int(os.getenv('PORT','5000')))
