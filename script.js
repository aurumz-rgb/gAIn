let pollingInterval = null;
let isFetching = false;
let isFrozen = false;
let currentInput = "";
let terminal_text = "";

const input = document.getElementById('ticker-input');
const body = document.getElementById('terminal-body');
const freezeBtn = document.getElementById('freeze-btn');

const BACKEND_URL = "http://localhost:8000"; 


setInterval(() => {
    const clock = document.getElementById('live-clock');
    if (clock) {
        const now = new Date();
        clock.innerText = now.toLocaleString('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
    }
}, 1000);

freezeBtn.addEventListener('click', () => {
    if (isFrozen) {
        isFrozen = false;
        freezeBtn.innerText = 'Freeze';
        if (currentInput) {
            fetchData(currentInput, false);
            pollingInterval = setInterval(() => {
                if (!isFrozen) fetchData(currentInput, false);
            }, 2000);
        }
    } else {
        isFrozen = true;
        freezeBtn.innerText = 'Resume';
        if (pollingInterval) clearInterval(pollingInterval);
    }
});

async function fetchData(inputVal, showLogs) {
    if (isFetching) return;
    isFetching = true;

    if (showLogs) {
        terminal_text = `[SYSTEM] Connecting to the backend SERVER...`;
        renderTerminalLogs();
    }

    try {
        const res = await fetch(`${BACKEND_URL}/get_live_data`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_input: inputVal, show_logs: showLogs })
        });

        if (showLogs) {
            const reader = res.body.getReader();
            const decoder = new TextDecoder();
            let buffer = '';

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');
                buffer = lines.pop();

                for (const line of lines) {
                    if (line.startsWith("LOG: ")) {
                        terminal_text += `\n${line.substring(5)}`;
                        renderTerminalLogs();
                    } else if (line.startsWith("FINAL: ")) {
                        const final_json = line.substring(7);
                        try {
                            const final_data = JSON.parse(final_json);
                            renderData(final_data);
                        } catch (e) {
                            console.error("Error parsing final JSON", e);
                        }
                    }
                }
            }
        } else {
            const data = await res.json();
            renderData(data);
        }
    } catch (e) {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
        body.innerHTML = `
            <div style="color: #ff5f56; font-size: 18px; line-height: 1.7;">
                <strong>⚠️  BACKEND IS NOT RUNNING...</strong><br><br>
                The frontend cannot reach the backend server.<br>
                Please run it on <strong>port 8000</strong>.<br><br>
                <span style="color: #aaa;">Start the backend from the project folder using:</span><br>
                <code style="color: rgb(59, 219, 107); background:#1a1a1a; padding:6px 10px; border-radius:4px; display:inline-block; margin-top:6px;">
                    python3 -m uvicorn main:app --reload --port 8000
                </code><br><br>
                <span style="color: #aaa;">Once the backend is running, type your ticker again and press ENTER.</span><br>
                <span style="color: #b49e57;">For more detailed information, please view the README.md file: <a href="https://github.com/aurumz-rgb/gAIn" target="_blank" style="color: #b49e57; text-decoration: underline;">https://github.com/aurumz-rgb/gAIn</a>.</span>
            </div>
        `;
    } finally {
        isFetching = false;
    }
}

function renderTerminalLogs() {
    body.innerHTML = `<pre style="white-space: pre-wrap; word-wrap: break-word; margin: 0; color: rgb(59, 219, 107);">${terminal_text}<span class="blink">_</span></pre>`;
    body.scrollTop = body.scrollHeight;
}

function renderData(data) {
    const reply = data.reply || "Error: No reply";
    const shortChart = data.short_chart_data || [];
    const longChart = data.long_chart_data || [];
    const targets = data.targets || {};

    const chunks = reply.split(/(\[CHART:[A-Z_]+\])/);


    const oldScrollTop = body.scrollTop;
    const isScrolledToBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 2;

    let html = '';
    chunks.forEach(chunk => {
        if (chunk.startsWith('[CHART:')) {
            const chartType = chunk.match(/CHART:([A-Z_]+)/)[1];
            const h = chartType === 'LONG_TERM' ? 400 : (chartType === 'PRICE' ? 350 : 250);
            html += `<div id="chart-${chartType}" style="width: 100%; height: ${h}px; margin: 10px 0; overflow: hidden;"></div>`;
        } else {
            html += marked.parse(chunk);
        }
    });

    body.innerHTML = html;


    if (isScrolledToBottom) {
        body.scrollTop = body.scrollHeight;
    } else {
        body.scrollTop = oldScrollTop;
    }

    if (chunks.includes('[CHART:PRICE]')) renderPriceChart('chart-PRICE', shortChart, targets);
    if (chunks.includes('[CHART:RSI]')) renderRsiChart('chart-RSI', shortChart);
    if (chunks.includes('[CHART:STOCH_RSI]')) renderStochRsiChart('chart-STOCH_RSI', shortChart);
    if (chunks.includes('[CHART:MACD]')) renderMacdChart('chart-MACD', shortChart);
    if (chunks.includes('[CHART:LONG_TERM]')) renderLongTermChart('chart-LONG_TERM', longChart);
}

function plotDefaults(h) {
    const w = document.getElementById('terminal-body').clientWidth - 40; 
    return {
        autosize: false, width: w, height: h,
        paper_bgcolor: 'rgba(0,0,0,0)', plot_bgcolor: 'rgba(0,0,0,0)',
        font: { color: '#ffffff', family: 'Menlo, monospace', size: 12 },
        margin: { l: 40, r: 20, t: 20, b: 30 }
    };
}

function renderPriceChart(id, data, targets) {
    if(!data || data.length === 0) return;
    const x = data.map(d => d.time);
    const traces = [
        { x: x, y: data.map(d => d.upper_band), mode: 'lines', line: {color: 'rgba(255,255,255,0.2)'}, name: 'Upper Band' },
        { x: x, y: data.map(d => d.lower_band), mode: 'lines', line: {color: 'rgba(255,255,255,0.2)'}, fill: 'tonexty', fillcolor: 'rgba(100,100,100,0.2)', name: 'Lower Band' },
        { x: x, y: data.map(d => d.vwap), mode: 'lines', line: {color: 'orange', width: 2}, name: 'VWAP' },
        { x: x, y: data.map(d => d.price), mode: 'lines', line: {color: 'rgb(59, 219, 107)', width: 2}, name: 'Price' }
    ];
    const shapes = [];
    if(targets.entry) shapes.push({type: 'line', x0: x[0], x1: x[x.length-1], y0: targets.entry, y1: targets.entry, line: {color: 'blue', dash: 'dash'}});
    if(targets.stop_loss) shapes.push({type: 'line', x0: x[0], x1: x[x.length-1], y0: targets.stop_loss, y1: targets.stop_loss, line: {color: 'red', dash: 'dash'}});
    if(targets.target) shapes.push({type: 'line', x0: x[0], x1: x[x.length-1], y0: targets.target, y1: targets.target, line: {color: 'green', dash: 'dash'}});
    Plotly.react(id, traces, {...plotDefaults(350), shapes: shapes, showlegend: false});
}

function renderRsiChart(id, data) {
    if(!data || data.length === 0) return;
    const x = data.map(d => d.time);
    const traces = [{ x: x, y: data.map(d => d.rsi), mode: 'lines', line: {color: 'purple', width: 2}, name: 'RSI' }];
    const shapes = [
        {type: 'line', x0: x[0], x1: x[x.length-1], y0: 70, y1: 70, line: {color: 'red', dash: 'dot'}},
        {type: 'line', x0: x[0], x1: x[x.length-1], y0: 30, y1: 30, line: {color: 'green', dash: 'dot'}}
    ];
    Plotly.react(id, traces, {...plotDefaults(250), shapes: shapes, yaxis: {range: [0, 100]}, showlegend: false});
}

function renderStochRsiChart(id, data) {
    if(!data || data.length === 0) return;
    const x = data.map(d => d.time);
    const traces = [{ x: x, y: data.map(d => d.stoch_rsi), mode: 'lines', line: {color: 'cyan', width: 2}, name: 'Stoch RSI' }];
    const shapes = [
        {type: 'line', x0: x[0], x1: x[x.length-1], y0: 0.8, y1: 0.8, line: {color: 'red', dash: 'dot'}},
        {type: 'line', x0: x[0], x1: x[x.length-1], y0: 0.2, y1: 0.2, line: {color: 'green', dash: 'dot'}}
    ];
    Plotly.react(id, traces, {...plotDefaults(250), shapes: shapes, yaxis: {range: [0, 1]}, showlegend: false});
}

function renderMacdChart(id, data) {
    if(!data || data.length === 0) return;
    const x = data.map(d => d.time);
    const hist = data.map(d => d.macd - d.signal);
    const traces = [
        { x: x, y: hist, type: 'bar', marker: {color: 'rgba(100,100,100,0.5)'}, name: 'Hist' },
        { x: x, y: data.map(d => d.macd), mode: 'lines', line: {color: 'blue', width: 2}, name: 'MACD' },
        { x: x, y: data.map(d => d.signal), mode: 'lines', line: {color: 'orange', width: 2}, name: 'Signal' }
    ];
    Plotly.react(id, traces, {...plotDefaults(250), showlegend: false});
}

function renderLongTermChart(id, data) {
    if(!data || data.length === 0) return;
    const x = data.map(d => d.time);
    const traces = [
        { x: x, y: data.map(d => d.price), mode: 'lines', line: {color: 'rgb(59, 219, 107)', width: 2}, name: 'Price' },
        { x: x, y: data.map(d => d.sma_50), mode: 'lines', line: {color: 'blue', dash: 'dash', width: 1.5}, name: '50 DMA' },
        { x: x, y: data.map(d => d.sma_200), mode: 'lines', line: {color: 'red', dash: 'dash', width: 1.5}, name: '200 DMA' }
    ];
    Plotly.react(id, traces, {...plotDefaults(400), showlegend: true});
}

input.addEventListener('keypress', function (e) {
    if (e.key === 'Enter') {
        const inputVal = input.value.trim();
        if (!inputVal) return;

        currentInput = inputVal;
        if (pollingInterval) clearInterval(pollingInterval);

        fetchData(inputVal, true);

        pollingInterval = setInterval(() => {
            if (!isFrozen) {
                fetchData(inputVal, false); 
            }
        }, 2000); 
    }
});