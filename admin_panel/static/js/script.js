// filepath: minecraft-server-manager/minecraft-server-manager/admin_panel/static/js/script.js
document.addEventListener('DOMContentLoaded', function() {
    // Add event listeners for tab functionality
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