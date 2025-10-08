# main.py — Domus AICI tout-en-un (API + Dashboard + PDF + Sauvegarde)
import io
import os
import json
from uuid import uuid4
from typing import List, Literal, Optional, Dict

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# PDF
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader

# ------------------------------------------------------------------------------
# App & Static
# ------------------------------------------------------------------------------
app = FastAPI(title="Domus AICI — Starter", version="1.0.0")
# Monte /static pour logo & (futurs) CSS
if os.path.isdir("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ------------------------------------------------------------------------------
# Modèles
# ------------------------------------------------------------------------------
class ClientIn(BaseModel):
    nom: str
    prenom: str
    email: str
    adresse: str

class ClientOut(ClientIn):
    id: str
    statut_aici: Literal["non_inscrit", "en_cours", "actif", "refuse"] = "non_inscrit"

class LignePrestation(BaseModel):
    libelle: str
    categorie_sap: Literal["entretien_maison", "petit_bricolage", "jardinage", "autre"]
    quantite: float
    prix_unitaire: float

class FactureIn(BaseModel):
    client_id: str
    lignes: List[LignePrestation] = Field(min_length=1)

class FactureOut(BaseModel):
    id: str
    client_id: str
    total_ttc: float
    montant_avance: float
    reste_a_charge: float
    statut_api: Literal["brouillon", "envoyee", "acceptee", "rejetee"] = "brouillon"
    ref_urssaf: Optional[str] = None
    message: Optional[str] = None

# ------------------------------------------------------------------------------
# "Base" en mémoire + Persistance JSON
# ------------------------------------------------------------------------------
DB_CLIENTS: Dict[str, ClientOut] = {}
DB_FACTURES: Dict[str, FactureOut] = {}
DB_PATH = "db_aici.json"

def save_db():
    data = {
        "clients": [c.model_dump() for c in DB_CLIENTS.values()],
        "factures": [f.model_dump() for f in DB_FACTURES.values()],
    }
    with open(DB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_db():
    if not os.path.exists(DB_PATH):
        return
    with open(DB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    DB_CLIENTS.clear()
    DB_FACTURES.clear()
    for c in data.get("clients", []):
        DB_CLIENTS[c["id"]] = ClientOut(**c)
    for fa in data.get("factures", []):
        DB_FACTURES[fa["id"]] = FactureOut(**fa)

def restore_db_from_dict(data: dict):
    """Remplace les données en mémoire par celles du JSON fourni, puis sauvegarde."""
    DB_CLIENTS.clear()
    DB_FACTURES.clear()
    for c in data.get("clients", []):
        DB_CLIENTS[c["id"]] = ClientOut(**c)
    for fa in data.get("factures", []):
        DB_FACTURES[fa["id"]] = FactureOut(**fa)
    save_db()

# Charge (si présent)
load_db()

# ------------------------------------------------------------------------------
# API JSON
# ------------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True}

@app.get("/", response_class=RedirectResponse)
def root_redirect():
    return RedirectResponse(url="/dashboard")

# Clients
@app.post("/clients", response_model=ClientOut)
def create_client(payload: ClientIn):
    cid = str(uuid4())
    client = ClientOut(id=cid, **payload.model_dump())
    DB_CLIENTS[cid] = client
    save_db()
    return client

@app.get("/clients")
def list_clients():
    return list(DB_CLIENTS.values())

@app.post("/clients/{client_id}/aici/enrol", response_model=ClientOut)
def enrol_aici(client_id: str):
    client = DB_CLIENTS.get(client_id)
    if not client:
        raise HTTPException(404, "Client introuvable")
    if client.statut_aici == "non_inscrit":
        client.statut_aici = "en_cours"
    elif client.statut_aici == "en_cours":
        client.statut_aici = "actif"
    DB_CLIENTS[client_id] = client
    save_db()
    return client

# Factures
@app.post("/factures", response_model=FactureOut)
def create_facture(payload: FactureIn):
    if payload.client_id not in DB_CLIENTS:
        raise HTTPException(404, "Client introuvable")
    total = sum(l.quantite * l.prix_unitaire for l in payload.lignes)
    fid = str(uuid4())
    facture = FactureOut(
        id=fid,
        client_id=payload.client_id,
        total_ttc=round(total, 2),
        montant_avance=0.0,
        reste_a_charge=round(total, 2),
        statut_api="brouillon",
    )
    DB_FACTURES[fid] = facture
    save_db()
    return facture

@app.get("/factures")
def list_factures():
    return list(DB_FACTURES.values())

@app.get("/factures/{facture_id}", response_model=FactureOut)
def get_facture(facture_id: str):
    facture = DB_FACTURES.get(facture_id)
    if not facture:
        raise HTTPException(404, "Facture introuvable")
    return facture

@app.post("/factures/{facture_id}/aici/send", response_model=FactureOut)
def send_facture(facture_id: str):
    facture = DB_FACTURES.get(facture_id)
    if not facture:
        raise HTTPException(404, "Facture introuvable")
    client = DB_CLIENTS.get(facture.client_id)
    if not client or client.statut_aici != "actif":
        raise HTTPException(400, "Client non inscrit AICI (statut actif requis)")
    facture.montant_avance = round(facture.total_ttc * 0.5, 2)
    facture.reste_a_charge = round(facture.total_ttc - facture.montant_avance, 2)
    facture.statut_api = "acceptee"
    facture.ref_urssaf = f"URSSAF-{facture.id[:8].upper()}"
    facture.message = "Simulation: avance immédiate appliquée (-50%)."
    DB_FACTURES[facture_id] = facture
    save_db()
    return facture

# Sauvegarde / Restauration
@app.get("/backup")
def backup_download():
    data = {
        "clients": [c.model_dump() for c in DB_CLIENTS.values()],
        "factures": [f.model_dump() for f in DB_FACTURES.values()],
    }
    buf = io.BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    return StreamingResponse(buf, media_type="application/json",
                             headers={"Content-Disposition": 'attachment; filename="db_aici.json"'})

@app.post("/restore")
async def restore_upload(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".json"):
        raise HTTPException(400, "Veuillez fournir un fichier .json")
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
        if not isinstance(data, dict) or "clients" not in data or "factures" not in data:
            raise ValueError("Structure JSON invalide (clés 'clients' et 'factures' requises)")
        restore_db_from_dict(data)
        return {"ok": True, "clients": len(DB_CLIENTS), "factures": len(DB_FACTURES)}
    except Exception as e:
        raise HTTPException(400, f"Import impossible: {e}")

# ------------------------------------------------------------------------------
# PDF
# ------------------------------------------------------------------------------
LOGO_PATH = os.path.join("static", "logo.png")
ENTREPRISE_NOM = "Domus Premium"
ENTREPRISE_EMAIL = "domuspremium35@gmail.com"
ENTREPRISE_TEL = "07 43 63 35 49"
ENTREPRISE_ADR = "23 rue du Loc’h, 35132 Vezin-le-Coquet"
MENTION_SAP = "Prestations éligibles aux Services à la Personne (SAP) — Avance immédiate crédit d’impôt 50 %."

def _draw_header(c):
    if os.path.exists(LOGO_PATH):
        try:
            img = ImageReader(LOGO_PATH)
            c.drawImage(img, 15*mm, 260*mm, width=35*mm, height=35*mm, preserveAspectRatio=True, mask='auto')
        except Exception:
            pass
    c.setFont("Helvetica-Bold", 14)
    c.drawString(60*mm, 285*mm, ENTREPRISE_NOM)
    c.setFont("Helvetica", 10)
    c.drawString(60*mm, 279*mm, ENTREPRISE_ADR)
    c.drawString(60*mm, 274*mm, f"Tél. {ENTREPRISE_TEL} — {ENTREPRISE_EMAIL}")

def _draw_footer(c):
    c.setFont("Helvetica", 8)
    c.drawString(15*mm, 12*mm, MENTION_SAP)
    c.setFont("Helvetica-Oblique", 8)
    c.drawRightString(200*mm, 12*mm, "Document généré automatiquement — Domus AICI")

@app.get("/factures/{facture_id}/pdf")
def facture_pdf(facture_id: str):
    facture = DB_FACTURES.get(facture_id)
    if not facture:
        return StreamingResponse(io.BytesIO(b"Facture introuvable"), media_type="text/plain", status_code=404)
    client = DB_CLIENTS.get(facture.client_id)

    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)

    # En-tête
    _draw_header(c)

    # Titre / méta
    c.setFont("Helvetica-Bold", 16)
    c.drawString(15*mm, 255*mm, "Facture")
    c.setFont("Helvetica", 10)
    c.drawString(15*mm, 249*mm, f"Référence: {facture.id[:8].upper()}    {facture.ref_urssaf or ''}")

    # Bloc client
    y = 240*mm
    c.setFont("Helvetica-Bold", 11)
    c.drawString(15*mm, y, "Client")
    c.setFont("Helvetica", 10)
    y -= 6*mm
    if client:
        c.drawString(15*mm, y, f"{client.prenom} {client.nom}"); y -= 5*mm
        c.drawString(15*mm, y, client.adresse); y -= 5*mm
        c.drawString(15*mm, y, client.email)
    else:
        c.drawString(15*mm, y, "(Client non trouvé)")
    y -= 10*mm

    # Montants
    c.setFont("Helvetica-Bold", 11)
    c.drawString(15*mm, y, "Récapitulatif")
    y -= 8*mm
    c.setFont("Helvetica", 10)
    c.drawString(15*mm, y, f"Total TTC : {facture.total_ttc:.2f} €"); y -= 6*mm
    c.drawString(15*mm, y, f"Avance immédiate (50 %) : −{facture.montant_avance:.2f} €"); y -= 6*mm
    c.setFont("Helvetica-Bold", 12)
    c.drawString(15*mm, y, f"Reste à charge : {facture.reste_a_charge:.2f} €"); y -= 8*mm
    c.setFont("Helvetica", 9)
    c.drawString(15*mm, y, f"Statut AICI : {facture.statut_api}    Réf. URSSAF : {facture.ref_urssaf or '—'}"); y -= 10*mm

    c.setFont("Helvetica", 9)
    c.drawString(15*mm, y, "Conditions : paiement du reste à charge à réception. L’avance immédiate est appliquée via l’Urssaf (dispositif AICI)."); y -= 5*mm
    c.drawString(15*mm, y, "En cas de rejet AICI, le montant correspondant restera dû par le client.")

    # Pied
    _draw_footer(c)

    c.showPage()
    c.save()

    buffer.seek(0)
    filename = f"facture_{facture.id[:8].upper()}.pdf"
    return StreamingResponse(buffer, media_type="application/pdf",
                             headers={"Content-Disposition": f'inline; filename="{filename}"'})

# ------------------------------------------------------------------------------
# Dashboard HTML (UI)
# ------------------------------------------------------------------------------
DASHBOARD_HTML = """
<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>Domus AICI — Tableau de bord</title>
  <style>
    body{font-family:ui-sans-serif,system-ui,Segoe UI,Roboto,Arial;margin:24px;background:#f6f7fb;color:#111}
    h1{font-size:22px;margin:0 0 16px}
    .grid{display:grid;gap:16px}
    .cols{grid-template-columns:1fr 1fr}
    .card{background:#fff;border-radius:12px;box-shadow:0 6px 20px rgba(0,0,0,.06);padding:16px}
    .title{font-weight:700;margin:0 0 8px}
    label{display:block;font-size:12px;color:#555;margin-top:8px}
    input,select{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:10px;background:#fff}
    button{padding:10px 14px;border:0;border-radius:10px;cursor:pointer}
    .btn{background:#111;color:#fff}
    .btn.secondary{background:#eef0f6;color:#111}
    table{width:100%;border-collapse:collapse;margin-top:8px}
    th,td{font-size:13px;padding:10px;border-bottom:1px solid #eee;text-align:left;vertical-align:top}
    .tag{padding:3px 10px;border-radius:999px;font-size:11px;background:#eef0f6;display:inline-block}
    .row{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
    .muted{color:#666}
    .mono{font-family:ui-monospace,Menlo,Consolas,monospace}
    .spacer{height:8px}
    @media (max-width:900px){ .cols{grid-template-columns:1fr} }
    .note{background:#ecfeff;border:1px dashed #67e8f9;color:#0e7490;padding:10px 12px;border-radius:10px;font-size:13px;margin-bottom:14px}
  </style>
</head>
<body>

  <div class="note">
    <b>Simulation locale.</b> Les données sont sauvegardées dans <code>db_aici.json</code> (même dossier que l’application).
  </div>

  <h1>Domus AICI — Tableau de bord</h1>

  <div class="grid cols">
    <!-- Créer un client -->
    <div class="card">
      <p class="title">Créer un client</p>
      <div class="grid">
        <div><label>Nom</label><input id="c_nom" placeholder="Dupont" /></div>
        <div><label>Prénom</label><input id="c_prenom" placeholder="Marie" /></div>
        <div><label>Email</label><input id="c_email" placeholder="marie.dupont@test.com" /></div>
        <div><label>Adresse</label><input id="c_adresse" placeholder="15 rue des Fleurs, Rennes" /></div>
      </div>
      <div class="spacer"></div>
      <button class="btn" onclick="createClient()">Enregistrer le client</button>
      <span id="c_msg" class="muted"></span>
    </div>

    <!-- Créer une facture -->
    <div class="card">
      <p class="title">Créer une facture</p>
      <div class="grid">
        <div><label>Client (ID)</label><input id="f_client_id" placeholder="colle l'ID client ici" /></div>
        <div><label>Libellé</label><input id="f_libelle" value="Taille de haie" /></div>
        <div>
          <label>Catégorie SAP</label>
          <select id="f_cat">
            <option value="jardinage">jardinage</option>
            <option value="petit_bricolage">petit_bricolage</option>
            <option value="entretien_maison">entretien_maison</option>
            <option value="autre">autre</option>
          </select>
        </div>
        <div><label>Quantité</label><input id="f_qte" type="number" value="1" /></div>
        <div><label>Prix unitaire (€)</label><input id="f_pu" type="number" value="200" /></div>
      </div>
      <div class="spacer"></div>
      <button class="btn" onclick="createFacture()">Créer la facture</button>
      <span id="f_msg" class="muted"></span>
    </div>
  </div>

  <div class="spacer"></div>

  <div class="grid cols">
    <!-- Clients -->
    <div class="card">
      <p class="title">Clients</p>
      <div class="row">
        <button class="btn secondary" onclick="loadClients()">Rafraîchir</button>
        <a class="btn" href="/backup" target="_blank">Télécharger la sauvegarde</a>
        <input id="restore_file" type="file" accept="application/json" />
        <button class="btn" onclick="restoreBackup()">Importer la sauvegarde</button>
      </div>
      <table id="tbl_clients">
        <thead><tr><th>Client</th><th>ID</th><th>Statut AICI</th><th>Actions</th></tr></thead>
        <tbody></tbody>
      </table>
    </div>

    <!-- Factures -->
    <div class="card">
      <p class="title">Factures</p>
      <div class="row">
        <button class="btn secondary" onclick="loadFactures()">Rafraîchir</button>
      </div>
      <table id="tbl_factures">
        <thead><tr>
          <th>Réf.</th><th>Client ID</th><th>Total</th><th>Avance</th><th>Reste</th><th>Statut</th><th>Actions</th>
        </tr></thead>
        <tbody></tbody>
      </table>
    </div>
  </div>

<script>
async function createClient(){
  const body = {
    nom: document.getElementById('c_nom').value || 'Dupont',
    prenom: document.getElementById('c_prenom').value || 'Marie',
    email: document.getElementById('c_email').value || 'marie.dupont@test.com',
    adresse: document.getElementById('c_adresse').value || 'Rennes'
  };
  const r = await fetch('/clients', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const json = await r.json();
  document.getElementById('c_msg').textContent = 'Client créé: ' + json.id;
  await loadClients();
  document.getElementById('f_client_id').value = json.id;
}

async function enrol(client_id){
  const r = await fetch(`/clients/${client_id}/aici/enrol`, {method:'POST'});
  if(r.ok){ await loadClients(); } else { alert('Erreur inscription AICI'); }
}

async function createFacture(){
  const body = {
    client_id: document.getElementById('f_client_id').value.trim(),
    lignes: [{
      libelle: document.getElementById('f_libelle').value,
      categorie_sap: document.getElementById('f_cat').value,
      quantite: parseFloat(document.getElementById('f_qte').value) || 1,
      prix_unitaire: parseFloat(document.getElementById('f_pu').value) || 0
    }]
  };
  const r = await fetch('/factures', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(body)});
  const json = await r.json();
  document.getElementById('f_msg').textContent = 'Facture créée: ' + json.id;
  await loadFactures();
}

async function sendAICI(fid){
  const r = await fetch(`/factures/${fid}/aici/send`, {method:'POST'});
  const json = await r.json();
  if(r.ok){ await loadFactures(); } else { alert(json.detail || 'Erreur envoi AICI'); }
}

async function restoreBackup(){
  const input = document.getElementById('restore_file');
  if(!input.files || !input.files[0]){ alert("Choisis un fichier JSON d'abord."); return; }
  const fd = new FormData();
  fd.append('file', input.files[0]);
  const r = await fetch('/restore', { method: 'POST', body: fd });
  const json = await r.json();
  if(r.ok){
    alert(`Import OK — Clients: ${json.clients}, Factures: ${json.factures}`);
    await loadClients(); await loadFactures();
  }else{
    alert(json.detail || 'Import impossible');
  }
}

function td(html){ const td = document.createElement('td'); td.innerHTML = html; return td; }

async function loadClients(){
  const r = await fetch('/clients');
  const arr = r.ok ? await r.json() : [];
  const tb = document.querySelector('#tbl_clients tbody');
  tb.innerHTML = '';
  arr.forEach(c=>{
    const tr = document.createElement('tr');
    tr.appendChild(td(`<div><b>${c.prenom} ${c.nom}</b><div class="muted">${c.email}<br>${c.adresse}</div></div>`));
    tr.appendChild(td(`<div class="mono">${c.id}</div>`));
    tr.appendChild(td(`<span class="tag">${c.statut_aici}</span>`));
    tr.appendChild(td(`<div class="row">
        <button class="btn secondary" onclick="enrol('${c.id}')">Inscrire/Avancer statut</button>
    </div>`));
    tb.appendChild(tr);
  });
}

async function loadFactures(){
  const r = await fetch('/factures');
  const arr = r.ok ? await r.json() : [];
  const tb = document.querySelector('#tbl_factures tbody');
  tb.innerHTML = '';
  arr.forEach(f=>{
    const tr = document.createElement('tr');
    tr.appendChild(td(`<div class="mono">${f.id.slice(0,8).toUpperCase()}</div>`));
    tr.appendChild(td(`<div class="mono">${f.client_id}</div>`));
    tr.appendChild(td(`${f.total_ttc.toFixed(2)} €`));
    tr.appendChild(td(`${f.montant_avance.toFixed(2)} €`));
    tr.appendChild(td(`<b>${f.reste_a_charge.toFixed(2)} €</b>`));
    tr.appendChild(td(`<span class="tag">${f.statut_api}</span><div class="muted mono">${f.ref_urssaf || ''}</div>`));
    tr.appendChild(td(`<div class="row">
       <button class="btn secondary" onclick="sendAICI('${f.id}')">Appliquer AICI (–50%)</button>
       <a class="btn" href="/factures/${f.id}/pdf" target="_blank">PDF</a>
    </div>`));
    tb.appendChild(tr);
  });
}

loadClients(); loadFactures();
</script>

</body>
</html>
"""

@app.get("/dashboard", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML

