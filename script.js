const BACKEND = 'http://127.0.0.1:5001';
let game = new Chess();
let board = null;
let history = [];
let highlighted = [];
let mode = 'analyse';

function initBoard() {
  board = Chessboard('board', {
    position: 'start',
    draggable: true,
    onDrop:    onDrop,
    onSnapEnd: () => board.position(game.fen()),
    
    pieceTheme: 'https://chessboardjs.com/img/chesspieces/wikipedia/{piece}.png'
  });
  updateTurn();
}

function onDrop(src, tgt) {
  clearHighlights();
  const move = game.move({ from: src, to: tgt, promotion: 'q' });
  if (!move) return 'snapback';
  syncFEN();
  updateTurn();
  history.push(move);
  renderHistory();
}

function clearHighlights() {
  document.querySelector('.square-' + highlighted[0])?.classList.remove('sq-highlight-from');
  document.querySelector('.square-' + highlighted[1])?.classList.remove('sq-highlight-to');
  highlighted = [];
}

function highlight(from, to) {
  clearHighlights();
  document.querySelector('.square-' + from)?.classList.add('sq-highlight-from');
  document.querySelector('.square-' + to)?.classList.add('sq-highlight-to');
  highlighted = [from, to];
}

function syncFEN() {
  document.getElementById('fenInput').value = game.fen();
}

function updateTurn() {
  const w = document.getElementById('turnW');
  const b = document.getElementById('turnB');
  
  if (game.turn() === 'w') {
    w.classList.remove('hidden');
    w.classList.add('active');
    b.classList.add('hidden');
    b.classList.remove('active');
  } else {
    b.classList.remove('hidden');
    b.classList.add('active');
    w.classList.add('hidden');
    w.classList.remove('active');
  }
}

function setStatus(type, msg) {
  const dot = document.getElementById('statusDot');
  const text = document.getElementById('statusText');
  if (dot) dot.className = 'status-dot ' + type;
  if (text) text.textContent = msg;
}

function loadFEN() {
  const fen = document.getElementById('fenInput').value.trim();
  const tmp = new Chess();
  if (!tmp.load(fen)) { setStatus('error', 'Invalid FEN'); return; }
  game.load(fen);
  board.position(fen);
  updateTurn();
  clearHighlights();
  setStatus('ready', 'Position loaded');
}

function resetBoard() {
  game.reset();
  board.start();
  syncFEN();
  updateTurn();
  clearHighlights();
  history = [];
  renderHistory();
  setStatus('ready', 'Ready to analyse');
  hide();
}

function flipBoard() { board.flip(); }

function undoMove() {
  const m = game.undo();
  if (!m) return;
  board.position(game.fen());
  syncFEN();
  updateTurn();
  clearHighlights();
  history.pop();
  renderHistory();
}

function renderHistory() {
  const g = document.getElementById('historyGrid');
  if (!history.length) {
    g.innerHTML = '<span style="font-size:12px; color:var(--text-dim);">No moves yet.</span>';
    return;
  }
  g.innerHTML = history.map((m, i) =>
    `<div class="h-move${i === history.length - 1 ? ' latest' : ''}">
      <span class="h-num">${i + 1}.</span>${m.san}
    </div>`
  ).join('');
}

function hide() {
  document.getElementById('emptyState').style.display = 'flex';
  ['moveCard','explainCard','historyCard'].forEach(id => {
    const el = document.getElementById(id);
    el.classList.add('hidden');
    el.classList.remove('is-visible');
  });
}

function show() {
  document.getElementById('emptyState').style.display = 'none';

  const moveCard = document.getElementById('moveCard');
  const explainCard = document.getElementById('explainCard');
  moveCard.classList.remove('hidden');
  explainCard.classList.remove('hidden');
  requestAnimationFrame(() => {
    moveCard.classList.add('is-visible');
    explainCard.classList.add('is-visible');
  });

  const historyCard = document.getElementById('historyCard');
  if (mode === 'history') {
    historyCard.classList.remove('hidden');
    requestAnimationFrame(() => historyCard.classList.add('is-visible'));
  } else {
    historyCard.classList.add('hidden');
    historyCard.classList.remove('is-visible');
  }
}

function setMode(m) {
  mode = m;
  document.getElementById('chipAnalyse').classList.toggle('active', m === 'analyse');
  document.getElementById('chipHistory').classList.toggle('active', m === 'history');
  const hc = document.getElementById('historyCard');
  const hasResult = !document.getElementById('moveCard').classList.contains('hidden');
  if (m === 'history' && hasResult) {
    hc.classList.remove('hidden');
    requestAnimationFrame(() => hc.classList.add('is-visible'));
  } else {
    hc.classList.add('hidden');
    hc.classList.remove('is-visible');
  }
}

async function analyse() {
  const btn = document.getElementById('analyseBtn');
  btn.disabled = true;
  btn.classList.add('loading');
  setStatus('loading', 'Asking Stockfish...');

  try {
    const res = await fetch(`${BACKEND}/analyse`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fen: game.fen() })
    });
    if (!res.ok) throw new Error('Server error');
    const data = await res.json();

    if (data.game_over) {
      document.getElementById('moveCard').classList.add('hidden');
      document.getElementById('moveCard').classList.remove('is-visible');

      const el = document.getElementById('explainText');
      el.textContent = data.explanation;
      el.className = 'explain-text';

      clearHighlights();
      document.getElementById('emptyState').style.display = 'none';
      const explainCard = document.getElementById('explainCard');
      explainCard.classList.remove('hidden');
      requestAnimationFrame(() => explainCard.classList.add('is-visible'));

      setStatus('ready', data.explanation);
      btn.disabled = false;
      btn.classList.remove('loading');
      return;
    }

    const from = data.best_move.slice(0, 2).toLowerCase();
    const to   = data.best_move.slice(2, 4).toLowerCase();

    document.getElementById('moveToken').textContent = data.san_move;
    document.getElementById('mFrom').textContent = from;
    document.getElementById('mTo').textContent   = to;

    let evalValue = data.evaluation;
    let pct = 50;

    if (evalValue.startsWith('M')) {
      pct = evalValue.includes('-') ? 2 : 98;
    } else {
      let pawns = parseFloat(evalValue);
      let centipawns = pawns * 100;
      let winPercent = 50 + 50 * (2 / (1 + Math.exp(-0.00368208 * centipawns)) - 1);
      pct = Math.max(2, Math.min(98, winPercent));
    }

    document.getElementById('evalFill').style.width  = pct.toFixed(1) + '%';
    document.getElementById('evalLabel').textContent = `Score: ${evalValue}`;

    const el = document.getElementById('explainText');
    el.textContent = data.explanation;
    el.className = 'explain-text';

    highlight(from, to);
    show();
    setStatus('ready', 'Best move: ' + data.san_move);

  } catch (e) {
    setStatus('error', 'Cannot reach server — is main.py running?');
  }

  btn.disabled = false;
  btn.classList.remove('loading');
}

initBoard();