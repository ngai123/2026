document.addEventListener("DOMContentLoaded", () => {
    
    // 1. Initialize Mermaid with dark theme
    mermaid.initialize({
        startOnLoad: true,
        theme: 'dark',
        themeVariables: {
            primaryColor: '#1e293b',
            primaryTextColor: '#e2e8f0',
            primaryBorderColor: '#3b82f6',
            lineColor: '#64748b',
            secondaryColor: '#0f111a',
            tertiaryColor: '#1a1d29'
        },
        flowchart: {
            curve: 'basis'
        }
    });

    // 2. Intersection Observer for scroll animations (reveal effect)
    const observerOptions = {
        root: null,
        rootMargin: '0px',
        threshold: 0.15
    };

    const observer = new IntersectionObserver((entries, observer) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('active');
                // Don't un-observe so it only happens once if preferred, 
                // but keeping it lets it animate every time. 
                // We'll un-observe for a cleaner one-time fade in.
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);

    const revealElements = document.querySelectorAll('.reveal');
    revealElements.forEach(el => observer.observe(el));

    // 3. Smooth Scrolling for Sidebar Links
    const navLinks = document.querySelectorAll('.nav-links a');
    
    navLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            e.preventDefault();
            const targetId = this.getAttribute('href').substring(1);
            const targetSection = document.getElementById(targetId);
            
            if (targetSection) {
                window.scrollTo({
                    top: targetSection.offsetTop - 40,
                    behavior: 'smooth'
                });
            }
        });
    });

    // 4. Update Active Sidebar Link on Scroll
    const sections = document.querySelectorAll('.section');
    
    window.addEventListener('scroll', () => {
        let current = '';
        const scrollY = window.pageYOffset;

        sections.forEach(section => {
            const sectionTop = section.offsetTop;
            const sectionHeight = section.clientHeight;
            if (scrollY >= (sectionTop - sectionHeight / 3)) {
                current = section.getAttribute('id');
            }
        });

        navLinks.forEach(link => {
            link.classList.remove('active');
            if (link.getAttribute('href').substring(1) === current) {
                link.classList.add('active');
            }
        });
    });
});
