document.addEventListener("DOMContentLoaded", function() {
    const activeTheme = localStorage.getItem('theme') || 'dark';
    document.documentElement.setAttribute('data-theme', activeTheme);

    const themeSelector = document.getElementById('theme-selector');
    if(themeSelector) {
        themeSelector.value = activeTheme;
        themeSelector.addEventListener('change', function(e) {
            const selected = e.target.value;
            document.documentElement.setAttribute('data-theme', selected);
            localStorage.setItem('theme', selected);
            
            fetch('/set-theme', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({theme: selected})
            });
        });
    }

    // Daily Claim Execution System
    const claimBtn = document.getElementById('claim-reward-btn');
    if(claimBtn) {
        claimBtn.addEventListener('click', function() {
            fetch('/daily-reward', { method: 'POST' })
            .then(res => res.json())
            .then(data => {
                if(data.status === 'success') {
                    alert(`Claimed successfully! Base: ₹${data.reward}, Bonus: ₹${data.bonus}. Total: ₹${data.total}`);
                    location.reload();
                } else {
                    alert(data.message);
                }
            });
        });
    }
});

// Lottery Scratch Realization Logic
let activeCardId = null;
function purchaseCard(cost) {
    fetch('/lottery/buy', {
        method: 'POST',
        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
        body: `cost=${cost}`
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') {
            activeCardId = data.card_id;
            const container = document.getElementById('scratch-card-area');
            container.innerHTML = '<div class="scratch-grid"></div>';
            const grid = container.querySelector('.scratch-grid');
            
            let scratchedCount = 0;
            data.cells.forEach((val, idx) => {
                const cell = document.createElement('div');
                cell.className = 'scratch-cell';
                cell.innerText = '?';
                cell.addEventListener('click', function() {
                    if(!cell.classList.contains('scratched')) {
                        cell.classList.add('scratched');
                        cell.innerText = val >= 0 ? `+₹${val}` : `-₹${Math.abs(val)}`;
                        cell.classList.add(val >= 0 ? 'positive' : 'negative');
                        scratchedCount++;
                        
                        if(scratchedCount === 16) {
                            finalizeCard();
                        }
                    }
                });
                grid.appendChild(cell);
            });
        } else {
            alert(data.message);
        }
    });
}

function finalizeCard() {
    fetch('/lottery/scratch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({card_id: activeCardId})
    })
    .then(res => res.json())
    .then(data => {
        if(data.status === 'success') {
            alert(`Card complete! Outcome context shift payload: ₹${data.total_won}`);
            location.reload();
        }
    });
}
