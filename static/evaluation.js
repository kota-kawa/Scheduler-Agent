document.addEventListener('DOMContentLoaded', () => {
    const scenarios = [
        "「洗剤を買う」というタスクを追加して。",
        "明日から明後日までの予定を教えて。",
        "「洗剤を買う」を「柔軟剤を買う」に名前を変えて。",
        "「柔軟剤を買う」タスク、完了しました。",
        "明日の15:30分から「歯医者」の予定を入れて。",
        "やっぱり「柔軟剤を買う」は削除して。そして、「歯医者」のタスクに「保険証を忘れない」というメモを追加しておいて。",
        "「筋トレ」という新しいルーチンを作って。月曜と木曜にやるよ。",
        "さっき作った「筋トレ」ルーチンに、「スクワット」というステップ（10分）を追加して。",
        "「筋トレ」ルーチン、やっぱり土曜日もやることにする。",
        "先週の金曜日の日報を見せて。"
    ];

    const tableBody = document.getElementById('evalTableBody');
    const template = document.getElementById('rowTemplate');

    if (!tableBody || !template) return;

    let conversationHistory = [];

    // Render Table
    scenarios.forEach((prompt, index) => {
        const clone = template.content.cloneNode(true);
        const tr = clone.querySelector('tr');
        
        tr.querySelector('.row-index').textContent = index + 1;
        tr.querySelector('.row-prompt').textContent = prompt;
        
        const runBtn = tr.querySelector('.run-btn');
        const successBtn = tr.querySelector('.success-btn');
        const failBtn = tr.querySelector('.fail-btn');
        const resultDiv = tr.querySelector('.result-content');
        const placeholder = tr.querySelector('.result-placeholder');
        const replyDiv = tr.querySelector('.agent-reply');
        const toolsDiv = tr.querySelector('.tool-calls');
        const judgeBtns = tr.querySelector('.judgment-btns');
        const judgeResult = tr.querySelector('.judgment-result');

        let lastResultData = null;

        runBtn.addEventListener('click', async () => {
            runBtn.disabled = true;
            runBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> 実行中...';
            placeholder.textContent = "実行中...";
            
            const currentMessages = [...conversationHistory, {role: 'user', content: prompt}];
            const payloadMessages = currentMessages.slice(-10);

            try {
                const response = await fetch('/api/evaluation/chat', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        messages: payloadMessages
                    })
                });
                const data = await response.json();
                
                if (data.error) {
                    throw new Error(data.error);
                }

                conversationHistory.push({role: 'user', content: prompt});
                conversationHistory.push({role: 'assistant', content: data.reply});

                // Show Result
                placeholder.classList.add('d-none');
                resultDiv.classList.remove('d-none');
                
                replyDiv.textContent = data.reply;
                
                let toolsText = "";
                if (data.actions && data.actions.length > 0) {
                    toolsText = "Tools Used:\n" + JSON.stringify(data.actions, null, 2);
                } else {
                    toolsText = "(No tool calls)";
                }
                if (data.results && data.results.length > 0) {
                    toolsText += "\n\nResults:\n" + data.results.join('\n');
                }
                if (data.errors && data.errors.length > 0) {
                    toolsText += "\n\nErrors:\n" + data.errors.join('\n');
                }

                toolsDiv.textContent = toolsText;
                
                lastResultData = {
                    prompt: prompt,
                    reply: data.reply,
                    tool_calls: data.actions || [],
                };

                runBtn.innerHTML = '<i class="bi bi-arrow-repeat"></i> 再実行';
                runBtn.disabled = false;
                judgeBtns.classList.remove('d-none');
                judgeResult.textContent = "";
                judgeResult.className = "judgment-result mt-2 fw-bold small";

                // Reload Calendar Frame if exists
                const calFrame = document.getElementById('calendarFrame');
                if (calFrame) {
                    calFrame.contentWindow.location.reload();
                }

            } catch (e) {
                console.error(e);
                placeholder.textContent = "エラー: " + e.message;
                runBtn.disabled = false;
                runBtn.innerHTML = '<i class="bi bi-play-fill"></i> 実行';
            }
        });

        const logResult = async (isSuccess) => {
            if (!lastResultData) return;
            const modelName = document.getElementById('modelSelect')?.value || "unknown";
            
            try {
                await fetch('/api/evaluation/log', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        model_name: modelName,
                        task_prompt: lastResultData.prompt,
                        agent_reply: lastResultData.reply,
                        tool_calls: lastResultData.tool_calls,
                        is_success: isSuccess
                    })
                });
                judgeBtns.classList.add('d-none');
                judgeResult.textContent = isSuccess ? "判定: OK" : "判定: NG";
                judgeResult.className = `judgment-result mt-2 fw-bold small text-${isSuccess ? 'success' : 'danger'}`;
            } catch(e) {
                alert("ログ保存失敗: " + e.message);
            }
        };

        successBtn.addEventListener('click', () => logResult(true));
        failBtn.addEventListener('click', () => logResult(false));

        tableBody.appendChild(tr);
    });

    // Global Buttons
    document.getElementById('seedBtn').addEventListener('click', async () => {
        if(!confirm("サンプルデータを追加しますか？（先週金曜の日報などが作成されます）")) return;
        try {
            const res = await fetch('/api/evaluation/seed', {method: 'POST'});
            const data = await res.json();
            alert(data.message || data.error);
            // Reload Calendar Frame if exists
            const calFrame = document.getElementById('calendarFrame');
            if (calFrame) {
                calFrame.contentWindow.location.reload();
            }
        } catch(e) {
            alert("エラー: " + e.message);
        }
    });

    // 明日〜明後日にサンプルデータを追加
    document.getElementById('seedPeriodBtn').addEventListener('click', async () => {
        const today = new Date();
        const tomorrow = new Date(today);
        tomorrow.setDate(tomorrow.getDate() + 1);
        const dayAfter = new Date(today);
        dayAfter.setDate(dayAfter.getDate() + 2);
        
        const formatDate = (d) => d.toISOString().split('T')[0];
        const startDate = formatDate(tomorrow);
        const endDate = formatDate(dayAfter);
        
        if(!confirm(`明日(${startDate})から明後日(${endDate})にサンプル予定を追加しますか？`)) return;
        try {
            const res = await fetch('/api/evaluation/seed_period', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({start_date: startDate, end_date: endDate})
            });
            const data = await res.json();
            alert(data.message || data.error);
            // Reload Calendar Frame if exists
            const calFrame = document.getElementById('calendarFrame');
            if (calFrame) {
                calFrame.contentWindow.location.reload();
            }
        } catch(e) {
            alert("エラー: " + e.message);
        }
    });

    document.getElementById('resetBtn').addEventListener('click', async () => {
        if(!confirm("本当に全データを削除しますか？")) return;
        try {
            const res = await fetch('/api/evaluation/reset', {method: 'POST'});
            const data = await res.json();
            conversationHistory = [];
            alert(data.message || data.error);
        } catch(e) {
            alert("エラー: " + e.message);
        }
    });

    // Run All (Mock for now or implement loop)
    document.getElementById('runAllBtn').addEventListener('click', () => {
        alert('順次実行はまだ実装されていません。各行の実行ボタンを押してください。');
    });
});
