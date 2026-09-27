/* landing.js - Handles the interactive mock playground */

document.addEventListener('DOMContentLoaded', () => {
    const mockInput = document.getElementById('mock-prompt-input');
    const mockRunBtn = document.getElementById('mock-run-btn');
    const mockTableBody = document.getElementById('mock-table-body');
    const mockLoading = document.getElementById('mock-loading');

    if (!mockRunBtn) return;

    // The original "dirty" state
    const originalData = [
        { id: 1, name: "john_doe_99", age: "32.0", email: "JOHN@EXAMPLE.COM" },
        { id: 2, name: "  Jane Smith  ", age: "28.5", email: "jane.s(at)example.com" },
        { id: 3, name: "bob johnson", age: "-45", email: "bob.j@example.com" }
    ];

    // Function to render table
    function renderTable(data, dropCol) {
        let html = '';
        data.forEach(row => {
            html += `<tr>`;
            if (dropCol !== 'id') html += `<td>${row.id}</td>`;
            if (dropCol !== 'name') html += `<td>${row.name}</td>`;
            if (dropCol !== 'age') html += `<td>${row.age}</td>`;
            if (dropCol !== 'email') html += `<td>${row.email}</td>`;
            html += `</tr>`;
        });
        return html;
    }

    // Process prompt and apply "AI" logic
    function applyMockAI(prompt) {
        let processedData = JSON.parse(JSON.stringify(originalData));
        let dropCol = null;
        let p = prompt.toLowerCase();
        
        const applyAll = p.includes('clean') && !p.includes('name') && !p.includes('age') && !p.includes('email');

        // Rule 1: Clean Names
        if (p.includes('name') || p.includes('format') || applyAll) {
            processedData.forEach(row => {
                let n = row.name.trim().replace(/_/g, ' ').replace(/[0-9]/g, '');
                // Title case
                row.name = n.split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(' ').trim();
            });
        }

        // Rule 2: Clean Emails
        if (p.includes('email') || applyAll) {
            processedData.forEach(row => {
                row.email = row.email.toLowerCase().replace('(at)', '@');
            });
        }

        // Rule 3: Clean Ages
        if (p.includes('age') || p.includes('number') || p.includes('math') || applyAll) {
            processedData.forEach(row => {
                let a = Math.abs(parseFloat(row.age));
                row.age = Math.round(a).toString();
            });
        }

        // Rule 4: Drop Columns
        if (p.includes('drop') || p.includes('remove') || p.includes('delete')) {
            if (p.includes('age')) dropCol = 'age';
            if (p.includes('name')) dropCol = 'name';
            if (p.includes('email')) dropCol = 'email';
            if (p.includes('id')) dropCol = 'id';
        }
        
        // Update headers if column dropped
        const thead = document.querySelector('.mock-table thead tr');
        if (thead) {
            thead.innerHTML = (dropCol !== 'id' ? `<th>ID</th>` : '') + 
                (dropCol !== 'name' ? `<th>Name</th>` : '') + 
                (dropCol !== 'age' ? `<th>Age</th>` : '') + 
                (dropCol !== 'email' ? `<th>Email</th>` : '');
        }

        return renderTable(processedData, dropCol);
    }

    mockRunBtn.addEventListener('click', () => {
        const prompt = mockInput.value.trim();
        if (!prompt) return;
        
        // 1. Show loading state
        mockTableBody.style.opacity = '0.3';
        mockTableBody.style.animation = 'none'; // reset anim
        mockLoading.classList.remove('hidden');
        mockRunBtn.disabled = true;
        mockRunBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>';

        // 2. Simulate AI processing time (0.8s for snappy feel)
        setTimeout(() => {
            // 3. Process logic dynamically based on user input
            const newHTML = applyMockAI(prompt);
            mockTableBody.innerHTML = newHTML;
            mockTableBody.style.opacity = '1';
            
            // 4. Reset UI
            mockLoading.classList.add('hidden');
            mockRunBtn.disabled = false;
            mockRunBtn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i> Run';
            
            // 5. Add a success highlight effect
            mockTableBody.style.animation = 'highlightRow 1s ease';
        }, 800);
    });
    
    // Allow 'Enter' key to run
    mockInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') mockRunBtn.click();
    });
});


// --- MOVED FROM INLINE SCRIPTS (CSP FIX) ---

document.addEventListener('DOMContentLoaded', () => {
    // 1. Slider Logic
    let slideIndex = 0;
    setInterval(() => {
        slideIndex = (slideIndex + 1) % 5;
        const slidesContainer = document.getElementById('demo-slider-slides');
        if (slidesContainer) {
            slidesContainer.style.transform = 'translateX(-' + (slideIndex * 100) + '%)';
        }
    }, 2000);

    // 2. Auth Check Logic
    fetch('/api/auth/me')
    .then(res => res.json())
    .then(data => {
        if(data.authenticated) {
            window.location.href = '/dashboard';
        }
    })
    .catch(err => console.error('Auth check failed:', err));
});
