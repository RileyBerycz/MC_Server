// filepath: minecraft-server-manager/minecraft-server-manager/admin_panel/static/js/script.js
document.addEventListener('DOMContentLoaded', function() {
    // Server control buttons
    const startButtons = document.querySelectorAll('.btn-primary[type="submit"]');
    const stopButtons = document.querySelectorAll('.btn-danger[type="submit"]');
    
    if (startButtons.length > 0) {
        startButtons.forEach(button => {
            button.addEventListener('click', function(event) {
                button.disabled = true;
                button.textContent = 'Starting...';
                // Don't prevent default to allow form submission
            });
        });
    }
    
    if (stopButtons.length > 0) {
        stopButtons.forEach(button => {
            button.addEventListener('click', function(event) {
                button.disabled = true;
                button.textContent = 'Stopping...';
                // Don't prevent default to allow form submission
            });
        });
    }

    // Add event listeners for form submissions
    const serverForms = document.querySelectorAll('form[action*="server"]');
    if (serverForms.length > 0) {
        serverForms.forEach(form => {
            form.addEventListener('submit', function() {
                const submitBtn = this.querySelector('button[type="submit"]');
                if (submitBtn) {
                    submitBtn.disabled = true;
                    if (this.action.includes('/start')) {
                        submitBtn.textContent = 'Starting...';
                    } else if (this.action.includes('/stop')) {
                        submitBtn.textContent = 'Stopping...';
                    } else if (this.action.includes('/delete')) {
                        submitBtn.textContent = 'Deleting...';
                    }
                }
            });
        });
    }
    
    // Tab functionality (if used)
    const tabLinks = document.querySelectorAll('.tablinks');
    if (tabLinks.length > 0) {
        tabLinks.forEach(tab => {
            tab.addEventListener('click', function(event) {
                openTab(event, this.getAttribute('data-tab'));
            });
        });
        
        // Open default tab on page load if it exists
        const defaultTab = document.getElementById("defaultOpen");
        if (defaultTab) {
            defaultTab.click();
        }
    }

    // Function to open a specific tab
    function openTab(evt, tabName) {
        var i, tabcontent, tablinks;
        tabcontent = document.getElementsByClassName("tabcontent");
        for (i = 0; i < tabcontent.length; i++) {
            tabcontent[i].style.display = "none";
        }
        tablinks = document.getElementsByClassName("tablinks");
        for (i = 0; i < tablinks.length; i++) {
            tablinks[i].className = tablinks[i].className.replace(" active", "");
        }
        if (document.getElementById(tabName)) {
            document.getElementById(tabName).style.display = "block";
            evt.currentTarget.className += " active";
        }
    }
});

// Add this function for the copy button

function copyToClipboard(text) {
    navigator.clipboard.writeText(text)
        .then(() => {
            // Create a temporary element to show feedback
            const btn = document.querySelector('.copy-btn');
            const originalText = btn.textContent;
            btn.textContent = 'Copied!';
            btn.style.backgroundColor = '#2196F3';
            
            // Reset after 2 seconds
            setTimeout(() => {
                btn.textContent = originalText;
                btn.style.backgroundColor = '';
            }, 2000);
        })
        .catch(err => {
            console.error('Failed to copy:', err);
            alert('Failed to copy. Please copy manually.');
        });
}