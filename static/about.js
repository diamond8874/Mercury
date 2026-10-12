// about.js

document.addEventListener('DOMContentLoaded', () => {
    // Accordion Logic
    const accordionItems = document.querySelectorAll('.accordion-item');

    accordionItems.forEach(item => {
        const trigger = item.querySelector('.accordion-trigger');
        const content = item.querySelector('.accordion-content');

        trigger.addEventListener('click', () => {
            const isActive = item.classList.contains('active');

            // Close all others
            accordionItems.forEach(otherItem => {
                otherItem.classList.remove('active');
                otherItem.querySelector('.accordion-content').style.maxHeight = null;
            });

            // Toggle current
            if (!isActive) {
                item.classList.add('active');
                content.style.maxHeight = content.scrollHeight + 40 + "px"; // 40px padding space
            }
        });
    });

    // Copy to Clipboard Logic
    const copyBtns = document.querySelectorAll('.copy-btn');
    const toast = document.getElementById('toast');

    copyBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            const textToCopy = btn.getAttribute('data-clipboard');
            navigator.clipboard.writeText(textToCopy).then(() => {
                showToast("Copied: " + textToCopy);
                
                // Visual feedback on button
                const icon = btn.querySelector('i');
                icon.className = "fa-solid fa-check";
                setTimeout(() => {
                    icon.className = "fa-regular fa-copy";
                }, 2000);
            }).catch(err => {
                console.error("Failed to copy", err);
            });
        });
    });

    function showToast(message) {
        toast.textContent = message;
        toast.classList.remove('hidden');
        setTimeout(() => {
            toast.classList.add('hidden');
        }, 3000);
    }
});
