// Utility functions
function copyToClipboard(text) {
    navigator.clipboard.writeText(text).then(function() {
      showAlert("Server address copied to clipboard", "success");
    }, function() {
      showAlert("Failed to copy address", "danger");
    });
  }
  
  function showAlert(message, type = "success") {
    const alertBox = document.createElement('div');
    alertBox.className = `alert alert-${type} alert-dismissible fade show`;
    alertBox.innerHTML = `
      ${message}
      <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
    `;
    
    // Insert at top of main content
    const container = document.querySelector('.container');
    if (container && container.firstChild) {
      container.insertBefore(alertBox, container.firstChild);
    } else {
      document.body.insertBefore(alertBox, document.body.firstChild);
    }
    
    // Auto-dismiss alert after 5 seconds
    setTimeout(() => alertBox.remove(), 5000);
  }
  
  // Tab functionality
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
    document.getElementById(tabName).style.display = "block";
    evt.currentTarget.className += " active";
  }
  
  // Server status management
  function refreshServerStatus() {
    const serverId = document.body.dataset.serverId;
    if (!serverId) return;
    
    fetch(`/api/server/${serverId}/status`)
      .then(response => response.json())
      .then(data => {
        updateServerStatus(data);
      })
      .catch(error => console.error('Error refreshing status:', error));
  }
  
  function updateServerStatus(data) {
    // Update status indicators
    const statusBadge = document.getElementById('server-status-badge');
    const connectionInfo = document.getElementById('connection-info');
    
    if (!statusBadge || !connectionInfo) return;
    
    if (data.status === "starting") {
      statusBadge.className = 'badge bg-warning';
      statusBadge.textContent = 'Starting';
      connectionInfo.innerHTML = 'Server is starting... Please wait.';
    } 
    else if (data.status === "running") {
      statusBadge.className = 'badge bg-success';
      statusBadge.textContent = 'Running';
      connectionInfo.innerHTML = `
        <h3>Server Address</h3>
        <div class="address-box">
          <code>${data.connection_info}</code>
          <button class="copy-btn" onclick="copyToClipboard('${data.connection_info}')">
            Copy
          </button>
        </div>
        <p class="connection-instructions">
          <strong>How to connect:</strong> Open Minecraft, click "Multiplayer", 
          then "Add Server" and paste this address
        </p>
      `;
    }
    else {
      statusBadge.className = 'badge bg-danger';
      statusBadge.textContent = 'Stopped';
      connectionInfo.innerHTML = 'Server is currently offline.';
    }
    
    // Update command response if available
    const cmdResponse = document.getElementById('command-response');
    if (cmdResponse && data.last_command_response) {
      cmdResponse.innerHTML = `<strong>Last Command Response:</strong><pre>${data.last_command_response}</pre>`;
      cmdResponse.classList.add('highlight-update');
      setTimeout(() => cmdResponse.classList.remove('highlight-update'), 1500);
    }
    
    // Update buttons visibility
    const startBtn = document.getElementById('start-server-btn');
    const stopBtn = document.getElementById('stop-server-btn');
    if (startBtn && stopBtn) {
      startBtn.style.display = data.is_active ? 'none' : 'inline-block';
      stopBtn.style.display = data.is_active ? 'inline-block' : 'none';
    }
  }
  
  // AJAX form handling
  function setupAjaxForms() {
    // Command form submission
    const commandForm = document.getElementById('command-form');
    const commandInput = document.getElementById('command-input');
  
    if (commandForm) {
      commandForm.addEventListener('submit', function(e) {
        e.preventDefault();
        
        // Show loading state
        commandForm.classList.add('loading');
        
        // Get form data
        const formData = new FormData(commandForm);
        
        // Submit via fetch API
        fetch(commandForm.action, {
          method: 'POST',
          body: formData
        })
        .then(response => response.ok ? 
          { status: 'success', message: `Command "${commandInput.value}" sent` } : 
          response.json())
        .then(data => {
          // Show success message
          showAlert(data.message || 'Command sent', data.status || 'success');
          
          // Clear input
          commandInput.value = '';
        })
        .catch(error => {
          console.error('Error:', error);
          showAlert('Error sending command', 'danger');
        })
        .finally(() => {
          // Remove loading state
          commandForm.classList.remove('loading');
          // Refresh status after a delay
          setTimeout(refreshServerStatus, 2000);
        });
      });
    }
    
    // Server action forms (start, stop, etc.)
    const actionForms = document.querySelectorAll('form[action*="/server/"]');
    actionForms.forEach(form => {
      // Skip forms that shouldn't use AJAX
      if (form.classList.contains('no-ajax')) return;
      
      form.addEventListener('submit', function(e) {
        e.preventDefault();
        const actionName = this.dataset.action || "server action";
        const formAction = this.action;
        
        // Add loading state to the button
        const submitButton = form.querySelector('button[type="submit"]');
        if (submitButton) {
          submitButton.disabled = true;
          submitButton.innerHTML = '<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Processing...';
        }
        
        // Submit via fetch
        fetch(formAction, {
          method: 'POST',
          body: new FormData(this)
        })
        .then(response => response.ok ? 
          { status: 'success', message: `${actionName} request sent` } : 
          response.json())
        .then(data => {
          showAlert(data.message || `${actionName} action processed`, data.status || 'success');
        })
        .catch(error => {
          console.error('Error:', error);
          showAlert(`Error processing ${actionName}`, 'danger');
        })
        .finally(() => {
          // Re-enable button after delay
          setTimeout(() => {
            if (submitButton) {
              submitButton.disabled = false;
              submitButton.innerHTML = submitButton.dataset.originalText || actionName;
            }
            // Refresh status
            refreshServerStatus();
          }, 2000);
        });
      });
      
      // Store original button text
      const button = form.querySelector('button[type="submit"]');
      if (button) button.dataset.originalText = button.innerHTML;
    });
  }
  
  // Initialize everything when DOM is ready
  document.addEventListener('DOMContentLoaded', function() {
    // Initialize tabs if present
    const defaultTab = document.getElementById("defaultOpen");
    if (defaultTab) defaultTab.click();
    
    // Set up AJAX form handling
    setupAjaxForms();
    
    // Start regular status polling
    const serverId = document.body.dataset.serverId;
    if (serverId) {
      refreshServerStatus();
      setInterval(refreshServerStatus, 5000);
    }
  });
  
  // WebSocket setup (if available)
  try {
    const serverId = document.body.dataset.serverId;
    if (typeof io !== 'undefined' && serverId) {
      const socket = io();
      
      socket.on('connect', function() {
        console.log('WebSocket connected');
      });
      
      socket.on('server_status_update', function(data) {
        if (data.server_id === serverId) {
          updateServerStatus(data);
        }
      });
    }
  } catch(e) {
    console.warn('WebSocket not available:', e);
  }