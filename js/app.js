(function(){
  const form = document.getElementById('aiciForm');
  const calcBtn = document.getElementById('calcBtn');
  const calcZone = document.getElementById('calcZone');
  const tbody = document.querySelector('#historyTable tbody');
  const printBtn = document.getElementById('printBtn');

  const EURO = new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR'});

  function format(n){ return EURO.format(Number(n||0)); }
  function today(){ return new Date().toISOString().slice(0,10); }

  function compute(){
    const montant = parseFloat(document.getElementById('montant').value || '0');
    if(isNaN(montant)||montant<=0){ calcZone.classList.add('hidden'); return; }
    const aici = Math.round(montant*0.5*100)/100;
    const reste = Math.round((montant - aici)*100)/100;
    calcZone.innerHTML = `
      <div><strong>Total TTC :</strong> ${format(montant)}</div>
      <div><strong>Avance immédiate (50%) :</strong> ${format(aici)}</div>
      <div><strong>Reste à charge client :</strong> ${format(reste)}</div>
      <small>Note : calcul démo simplifié, sans plafonds ni cas particuliers.</small>
    `;
    calcZone.classList.remove('hidden');
    return { montant, aici, reste };
  }

  calcBtn.addEventListener('click', compute);

  form.addEventListener('submit', (e)=>{
    e.preventDefault();
    const c = document.getElementById('client').value.trim();
    const p = document.getElementById('prestation').value.trim();
    const d = document.getElementById('datePrest').value || today();
    const m = parseFloat(document.getElementById('montant').value||'0');
    if(!c || !p || !m){ alert('Merci de compléter le formulaire.'); return; }
    const calc = compute();
    const tr = document.createElement('tr');
    tr.innerHTML = `<td>${d}</td><td>${c}</td><td>${p}</td><td>${format(m)}</td><td>${format(calc.aici)}</td><td>Transmis (démo)</td>`;
    tbody.prepend(tr);
    form.reset();
    calcZone.classList.add('hidden');
    alert('Dossier transmis (démo). Aucun envoi réel à l’URSSAF n’est effectué.');
  });

  // Seed demo rows
  const seed = [
    {d:'2025-10-12', c:'Mme Dupont', p:'Entretien jardin', m:80},
    {d:'2025-10-05', c:'M. Martin', p:'Bricolage léger', m:120}
  ];
  seed.forEach(x=>{
    const tr = document.createElement('tr');
    const aici = x.m*0.5;
    tr.innerHTML = `<td>${x.d}</td><td>${x.c}</td><td>${x.p}</td><td>${format(x.m)}</td><td>${format(aici)}</td><td>Réglé (démo)</td>`;
    tbody.appendChild(tr);
  });

  // Print to PDF (for evidence to URSSAF if needed)
  printBtn?.addEventListener('click', ()=> window.print());
})();
