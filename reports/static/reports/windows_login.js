(function () {
    const root = document.querySelector("[data-windows-login]");
    if (!root) return;

    const start = root.querySelector("[data-windows-start]");
    const form = root.querySelector("[data-windows-form]");
    const usernameInput = form.querySelector("input[name='username']");
    const passwordInput = form.querySelector("input[name='password']");
    const usernameField = form.querySelector("[data-windows-username-field]");
    const accountSummary = form.querySelector("[data-windows-account-summary]");
    const accountName = form.querySelector("[data-windows-account-name]");
    const change = form.querySelector("[data-windows-change]");
    const passwordToggle = form.querySelector("[data-password-toggle]");
    const storageKey = "mining360.windowsUsername";

    function rememberedUsername() {
        try {
            return window.localStorage.getItem(storageKey) || "";
        } catch (_) {
            return "";
        }
    }

    function showUsernameEditor() {
        usernameField.hidden = false;
        accountSummary.hidden = true;
        usernameInput.focus();
        usernameInput.select();
    }

    function showCredentials() {
        const username = usernameInput.value.trim();
        form.hidden = false;
        start.hidden = true;
        start.setAttribute("aria-expanded", "true");
        if (username) {
            accountName.textContent = username;
            accountSummary.hidden = false;
            usernameField.hidden = true;
            passwordInput.focus();
        } else {
            showUsernameEditor();
        }
    }

    const serverUsername = (root.dataset.serverUsername || "").trim();
    usernameInput.value = usernameInput.value.trim() || serverUsername || rememberedUsername();
    start.addEventListener("click", showCredentials);
    change.addEventListener("click", showUsernameEditor);
    passwordToggle.addEventListener("click", function () {
        const visible = passwordInput.type === "text";
        passwordInput.type = visible ? "password" : "text";
        passwordToggle.setAttribute("aria-pressed", String(!visible));
        passwordToggle.setAttribute("aria-label", visible ? "Show password" : "Hide password");
        passwordToggle.title = visible ? "Show password" : "Hide password";
        passwordInput.focus();
    });
    form.addEventListener("submit", function () {
        const username = usernameInput.value.trim();
        if (!username) return;
        try {
            window.localStorage.setItem(storageKey, username);
        } catch (_) {
            // Browser storage can be disabled without blocking authentication.
        }
    });

    if (document.querySelector(".login-messages")) showCredentials();
}());
