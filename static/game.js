// ── Constants ──────────────────────────────────────────────────────────────
const CELL_SIZE = 22;
const ROW_HEIGHT = 38;
const OFFSET_X = 96;       // tuned so board center lands at canvas center
const OFFSET_Y = 56;
const HOLE_RADIUS = 14;
const PIECE_RADIUS = 12;

// Board center in pixel coords: toPixel(8, 12) = (12*22+96, 8*38+56) = (360, 360)
const CENTER_X = 360;
const CENTER_Y = 360;

// Rotation per slot so each player's home triangle is at the bottom.
// Slot N sits at angular position N*60° from the top; rotating by
// (180° - N*60°) moves it to the bottom.
const SLOT_ROTATION = {
    0:  Math.PI,            // 180°
    1:  2 * Math.PI / 3,    // 120°
    2:  Math.PI / 3,        //  60°
    3:  0,                  //   0°  (already at bottom)
    4: -Math.PI / 3,        // -60°
    5: -2 * Math.PI / 3,    // -120°
};

const SLOT_COLORS = {
    0: '#e74c3c',
    1: '#3498db',
    2: '#2ecc71',
    3: '#f1c40f',
    4: '#9b59b6',
    5: '#e67e22',
};

// ── State ──────────────────────────────────────────────────────────────────
let ws = null;
let playerId = null;
let myIndex = null;
let mySlot = null;
let isHost = false;
let boardDef = null;
let gameState = null;
let selectedPos = null;
let validMoves = [];
let posSet = new Set();

// ── DOM refs ───────────────────────────────────────────────────────────────
const lobby = document.getElementById('lobby');
const waiting = document.getElementById('waiting');
const gameArea = document.getElementById('game-area');
const gameOverlay = document.getElementById('game-over');
const canvas = document.getElementById('game-canvas');
const ctx = canvas.getContext('2d');
const toastEl = document.getElementById('toast');

// ── WebSocket ──────────────────────────────────────────────────────────────
function connect(callback) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        callback();
        return;
    }
    if (ws) ws.close();

    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${location.host}/ws`);

    ws.onopen = () => {
        console.log('Connected');
        callback();
    };

    ws.onmessage = (event) => {
        handleMessage(JSON.parse(event.data));
    };

    ws.onclose = () => {
        console.log('Disconnected');
        showToast('Disconnected from server');
    };

    ws.onerror = () => showToast('Connection error');
}

function sendMsg(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify(obj));
    }
}

// ── Message handler ────────────────────────────────────────────────────────
function handleMessage(data) {
    switch (data.type) {
        case 'created':
            playerId = data.player_id;
            isHost = true;
            myIndex = 0;
            boardDef = data.board_definition;
            buildPosSet();
            gameState = data.state;
            showWaiting(data.password);
            break;

        case 'joined':
            playerId = data.player_id;
            isHost = false;
            boardDef = data.board_definition;
            buildPosSet();
            gameState = data.state;
            myIndex = data.state.players.length - 1;
            showWaiting(null);
            break;

        case 'player_joined':
        case 'player_left':
            gameState = data.state;
            updateWaitingRoom();
            break;

        case 'started':
            gameState = data.state;
            resolveMySlot();
            selectedPos = null;
            validMoves = [];
            showGame();
            draw();
            break;

        case 'valid_moves':
            validMoves = data.moves;
            draw();
            break;

        case 'hints_toggled':
            gameState = data.state;
            updateHintsButton();
            // Clear any displayed hints if turned off
            if (!gameState.show_hints) { validMoves = []; }
            draw();
            break;

        case 'moved':
            gameState = data.state;
            selectedPos = null;
            validMoves = [];
            draw();
            updateTurnInfo();
            break;

        case 'game_over':
            gameState = data.state;
            selectedPos = null;
            validMoves = [];
            draw();
            showGameOver(data.winner_name, data.reason);
            break;

        case 'stopped':
            showToast(data.message, true);
            resetToLobby();
            break;

        case 'error':
            showToast(data.message);
            break;
    }
}

// ── Slot resolution ────────────────────────────────────────────────────────
function resolveMySlot() {
    if (!gameState || myIndex === null) return;
    if (myIndex < gameState.players.length) {
        mySlot = gameState.players[myIndex].slot;
    }
}

// ── UI transitions ─────────────────────────────────────────────────────────
function show(el) { el.classList.remove('hidden'); }
function hide(el) { el.classList.add('hidden'); }

function showWaiting(password) {
    hide(lobby); hide(gameArea); hide(gameOverlay);
    show(waiting);
    if (password) {
        document.getElementById('show-password').textContent = password;
    }
    updateWaitingRoom();
}

function updateWaitingRoom() {
    const list = document.getElementById('player-list');
    list.innerHTML = '';
    if (!gameState) return;

    gameState.players.forEach((p, i) => {
        const li = document.createElement('li');
        li.style.background = 'rgba(255,255,255,0.05)';
        const slotAssignments = {
            1: [0], 2: [0,3], 3: [0,2,4], 4: [0,1,3,4], 5: [0,1,3,4,5], 6: [0,1,2,3,4,5]
        };
        const n = gameState.players.length;
        const slots = slotAssignments[n] || [];
        const slot = i < slots.length ? slots[i] : i;
        const color = SLOT_COLORS[slot] || '#888';
        li.innerHTML = `<span class="player-dot" style="background:${color}"></span> ${esc(p.name)}${i === 0 ? ' (host)' : ''}`;
        if (!p.connected) li.style.opacity = '0.4';
        list.appendChild(li);
    });

    const btn = document.getElementById('btn-start');
    const n = gameState.players.length;
    if (isHost && [2,3,4,6].includes(n)) {
        btn.disabled = false;
        btn.textContent = `Start Game (${n} players)`;
    } else if (isHost) {
        btn.disabled = true;
        btn.textContent = `Need 2, 3, 4, or 6 players (${n} now)`;
    } else {
        btn.disabled = true;
        btn.textContent = 'Waiting for host to start...';
    }
    document.getElementById('btn-stop-lobby').classList.toggle('hidden', !isHost);
}

function showGame() {
    hide(lobby); hide(waiting); hide(gameOverlay);
    show(gameArea);
    document.getElementById('btn-stop-game').classList.toggle('hidden', !isHost);
    document.getElementById('btn-toggle-hints').classList.toggle('hidden', !isHost);
    updateHintsButton();
    buildLegend();
    updateTurnInfo();
}

function updateHintsButton() {
    const btn = document.getElementById('btn-toggle-hints');
    if (!gameState) return;
    btn.textContent = gameState.show_hints ? 'Hints: ON' : 'Hints: OFF';
}

function showGameOver(winnerName, reason) {
    const text = document.getElementById('winner-text');
    const detail = document.getElementById('winner-detail');
    if (reason === 'disconnect') {
        text.textContent = 'Game Over';
        detail.textContent = `${winnerName} wins (other players disconnected)`;
    } else {
        text.textContent = `${winnerName} Wins!`;
        detail.textContent = 'All pieces reached the goal triangle.';
    }
    show(gameOverlay);
    hide(document.getElementById('btn-stop-game'));
}

function resetToLobby() {
    playerId = null; isHost = false; boardDef = null;
    gameState = null; selectedPos = null; validMoves = [];
    mySlot = null; myIndex = null;
    show(lobby); hide(waiting); hide(gameArea); hide(gameOverlay);
    if (ws) { ws.close(); ws = null; }
}

// ── Legend & turn info ─────────────────────────────────────────────────────
function buildLegend() {
    const legend = document.getElementById('player-legend');
    legend.innerHTML = '';
    if (!gameState) return;
    gameState.players.forEach(p => {
        const div = document.createElement('div');
        div.className = 'legend-item';
        div.innerHTML = `<span class="legend-dot" style="background:${SLOT_COLORS[p.slot]||'#888'}"></span> ${esc(p.name)}`;
        legend.appendChild(div);
    });
}

function updateTurnInfo() {
    const el = document.getElementById('turn-info');
    if (!gameState || gameState.phase !== 'playing') { el.textContent = ''; return; }
    const cur = gameState.players[gameState.current_turn];
    const color = SLOT_COLORS[cur.slot] || '#888';
    const mine = gameState.current_turn === myIndex;
    el.innerHTML = mine
        ? `<span style="color:${color}">Your turn!</span> Select a piece to move.`
        : `<span style="color:${color}">${esc(cur.name)}</span>'s turn`;
}

// ── Board helpers ──────────────────────────────────────────────────────────
function buildPosSet() {
    posSet.clear();
    if (!boardDef) return;
    for (const [r, c] of boardDef.positions) posSet.add(`${r},${c}`);
}

function toPixelBase(row, col) {
    return { x: col * CELL_SIZE + OFFSET_X, y: row * ROW_HEIGHT + OFFSET_Y };
}

function toPixel(row, col) {
    const base = toPixelBase(row, col);
    const angle = mySlot !== null ? (SLOT_ROTATION[mySlot] || 0) : 0;
    if (angle === 0) return base;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    const dx = base.x - CENTER_X;
    const dy = base.y - CENTER_Y;
    return {
        x: CENTER_X + dx * cos - dy * sin,
        y: CENTER_Y + dx * sin + dy * cos,
    };
}

function fromPixel(px, py) {
    let best = null, bestDist = Infinity;
    if (!boardDef) return null;
    for (const [r, c] of boardDef.positions) {
        const { x, y } = toPixel(r, c);
        const d = Math.hypot(px - x, py - y);
        if (d < bestDist && d < HOLE_RADIUS + 8) { bestDist = d; best = [r, c]; }
    }
    return best;
}

function getTriangleSlot(row, col) {
    if (!boardDef) return null;
    for (const [slot, positions] of Object.entries(boardDef.triangles)) {
        for (const [r, c] of positions) {
            if (r === row && c === col) return parseInt(slot);
        }
    }
    return null;
}

// ── Drawing ────────────────────────────────────────────────────────────────
function draw() {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    if (!boardDef || !gameState || gameState.phase !== 'playing') return;
    drawHoles();
    drawPieces();
    drawSelection();
    drawValidMoves();
}

function drawHoles() {
    for (const [r, c] of boardDef.positions) {
        const { x, y } = toPixel(r, c);
        const tri = getTriangleSlot(r, c);
        ctx.beginPath();
        ctx.arc(x, y, HOLE_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = tri !== null ? hexToRgba(SLOT_COLORS[tri], 0.15) : 'rgba(255,255,255,0.04)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.15)';
        ctx.lineWidth = 1;
        ctx.stroke();
    }
}

function drawPieces() {
    for (const [key, slot] of Object.entries(gameState.board)) {
        const [r, c] = key.split(',').map(Number);
        const { x, y } = toPixel(r, c);
        const color = SLOT_COLORS[slot];

        // Shadow
        ctx.beginPath();
        ctx.arc(x + 1, y + 2, PIECE_RADIUS, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(0,0,0,0.3)';
        ctx.fill();

        // Piece
        ctx.beginPath();
        ctx.arc(x, y, PIECE_RADIUS, 0, Math.PI * 2);
        const grad = ctx.createRadialGradient(x - 3, y - 3, 2, x, y, PIECE_RADIUS);
        grad.addColorStop(0, lighten(color, 50));
        grad.addColorStop(1, color);
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.strokeStyle = 'rgba(255,255,255,0.25)';
        ctx.lineWidth = 1.5;
        ctx.stroke();
    }
}

function drawSelection() {
    if (!selectedPos) return;
    const { x, y } = toPixel(selectedPos[0], selectedPos[1]);
    ctx.beginPath();
    ctx.arc(x, y, PIECE_RADIUS + 5, 0, Math.PI * 2);
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 3;
    ctx.stroke();
}

function drawValidMoves() {
    if (gameState && !gameState.show_hints) return;
    for (const [r, c] of validMoves) {
        const { x, y } = toPixel(r, c);
        ctx.beginPath();
        ctx.arc(x, y, HOLE_RADIUS - 2, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(100, 255, 100, 0.3)';
        ctx.fill();
        ctx.strokeStyle = 'rgba(100, 255, 100, 0.7)';
        ctx.lineWidth = 2;
        ctx.stroke();
    }
}

// ── Canvas click ───────────────────────────────────────────────────────────
canvas.addEventListener('click', (e) => {
    if (!gameState || gameState.phase !== 'playing') return;
    if (gameState.current_turn !== myIndex) return;

    const rect = canvas.getBoundingClientRect();
    const sx = canvas.width / rect.width;
    const sy = canvas.height / rect.height;
    const px = (e.clientX - rect.left) * sx;
    const py = (e.clientY - rect.top) * sy;

    const pos = fromPixel(px, py);
    if (!pos) { selectedPos = null; validMoves = []; draw(); return; }

    const [r, c] = pos;
    const key = `${r},${c}`;

    // Click a valid move destination
    if (selectedPos && validMoves.some(m => m[0] === r && m[1] === c)) {
        sendMsg({ type: 'move', from: selectedPos, to: [r, c] });
        selectedPos = null; validMoves = []; draw();
        return;
    }

    // Click own piece
    if (gameState.board[key] === mySlot) {
        selectedPos = [r, c]; validMoves = []; draw();
        sendMsg({ type: 'get_moves', row: r, col: c });
        return;
    }

    // Click elsewhere
    selectedPos = null; validMoves = []; draw();
});

// ── Button handlers ────────────────────────────────────────────────────────
document.getElementById('btn-create').addEventListener('click', () => {
    const name = document.getElementById('player-name').value.trim();
    const password = document.getElementById('game-password').value.trim();
    if (!name || !password) { showToast('Enter your name and a password'); return; }
    myIndex = 0;
    connect(() => sendMsg({ type: 'create', name, password }));
});

document.getElementById('btn-join').addEventListener('click', () => {
    const name = document.getElementById('player-name').value.trim();
    const password = document.getElementById('game-password').value.trim();
    if (!name || !password) { showToast('Enter your name and the game password'); return; }
    connect(() => sendMsg({ type: 'join', name, password }));
});

document.getElementById('btn-start').addEventListener('click', () => sendMsg({ type: 'start' }));
document.getElementById('btn-toggle-hints').addEventListener('click', () => sendMsg({ type: 'toggle_hints' }));
document.getElementById('btn-stop-lobby').addEventListener('click', () => sendMsg({ type: 'stop' }));
document.getElementById('btn-stop-game').addEventListener('click', () => {
    if (confirm('Stop the game?')) sendMsg({ type: 'stop' });
});
document.getElementById('btn-new-game').addEventListener('click', resetToLobby);

document.getElementById('password-display').addEventListener('click', () => {
    const pw = document.getElementById('show-password').textContent;
    navigator.clipboard.writeText(pw).then(() => showToast('Password copied!', true)).catch(() => {});
});

// Enter key submits
document.getElementById('game-password').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') document.getElementById('btn-join').click();
});

// ── Utilities ──────────────────────────────────────────────────────────────
function showToast(msg, isInfo) {
    toastEl.textContent = msg;
    toastEl.className = isInfo ? 'show info' : 'show';
    clearTimeout(toastEl._t);
    toastEl._t = setTimeout(() => { toastEl.className = ''; }, 3000);
}

function esc(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
}

function hexToRgba(color, alpha) {
    const c = parseColor(color);
    return c ? `rgba(${c[0]},${c[1]},${c[2]},${alpha})` : `rgba(128,128,128,${alpha})`;
}

function lighten(color, amt) {
    const c = parseColor(color);
    if (!c) return color;
    return `rgb(${Math.min(255,c[0]+amt)},${Math.min(255,c[1]+amt)},${Math.min(255,c[2]+amt)})`;
}

const _colorCache = {};
function parseColor(color) {
    if (_colorCache[color]) return _colorCache[color];
    const el = document.createElement('div');
    el.style.color = color;
    document.body.appendChild(el);
    const m = getComputedStyle(el).color.match(/(\d+),\s*(\d+),\s*(\d+)/);
    document.body.removeChild(el);
    if (m) {
        _colorCache[color] = [+m[1], +m[2], +m[3]];
        return _colorCache[color];
    }
    return null;
}
