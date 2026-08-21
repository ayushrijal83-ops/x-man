document.addEventListener('DOMContentLoaded', function() {
    console.log('HackForge initialized');
    
    setTimeout(function() {
        document.querySelectorAll('.alert').forEach(function(alert) {
            alert.style.opacity = '0';
            alert.style.transition = 'opacity 0.5s';
            setTimeout(function() {
                alert.remove();
            }, 500);
        });
    }, 5000);
});

const API = {
    async get(url) {
        const response = await fetch(url);
        return response.json();
    },
    
    async post(url, data) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': document.querySelector('meta[name="csrf-token"]').content
            },
            body: JSON.stringify(data)
        });
        return response.json();
    },
    
    async checkHealth() {
        try {
            const health = await this.get('/api/health');
            console.log('Health check:', health);
            return health;
        } catch (error) {
            console.error('Health check failed:', error);
            return null;
        }
    }
};

window.API = API;