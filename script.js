"use strict";

// ==========================================
// 1. CONTROLLED RECOVERY TEST
// ==========================================
const recoveryButton = document.getElementById("recoveryButton");

if (recoveryButton) {
    recoveryButton.addEventListener("click", async function () {
        const status = document.getElementById("healStatus");
        const message = document.getElementById("healMessage");

        recoveryButton.disabled = true;

        if (status) status.textContent = "Running recovery test...";
        if (message) message.textContent = "Testing the controlled failure.";

        try {
            const response = await fetch("/api/error-lab/generate", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ type: "service" })
            });

            if (response.redirected) {
                throw new Error("Redirected to login. Please sign in as administrator.");
            }

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.message || "Recovery test failed");
            }

            if (status) {
                status.textContent = data.status || "Test completed";
            }

            if (message) {
                message.textContent =
                    `Detection: ${data.detection_ms ?? "—"} ms | ` +
                    `Recovery: ${data.recovery_ms ?? "—"} ms. ` +
                    (data.message || "");
            }

            await loadIncidentTimeline();
        } catch (error) {
            if (status) status.textContent = "Test failed";
            if (message) message.textContent = error.message;
        } finally {
            recoveryButton.disabled = false;
        }
    });
}


// ==========================================
// 2. DASHBOARD SEARCH
// ==========================================
const search = document.getElementById("search");

if (search) {
    search.addEventListener("input", function () {
        const query = search.value.toLowerCase().trim();

        document.querySelectorAll(".card, .panel").forEach(function (item) {
            item.hidden = !item.textContent.toLowerCase().includes(query);
        });
    });
}


// ==========================================
// 3. STUDENT FAQ ASSISTANT
// ==========================================
const chatForm = document.getElementById("chatForm");

if (chatForm) {
    chatForm.addEventListener("submit", function (event) {
        event.preventDefault();

        const input = document.getElementById("chatInput");
        const messages = document.getElementById("chatMessages");

        if (!input || !messages) return;

        const originalQuestion = input.value.trim();
        const question = originalQuestion.toLowerCase();

        if (!originalQuestion) return;

        let answer =
            "Please ask about attendance, marks, assignments or timetable.";

        if (question.includes("attendance")) {
            answer = "Your sample attendance is 92% (23 of 25 classes).";
        } else if (question.includes("mark")) {
            answer = "Your sample overall marks are 78%.";
        } else if (question.includes("assignment")) {
            answer = "You have 3 pending assignments in this demo.";
        } else if (
            question.includes("timetable") ||
            question.includes("class")
        ) {
            answer = "Your next sample class is Web Development at 9:00 AM.";
        }

        const userMessage = document.createElement("p");
        userMessage.textContent = "You: " + originalQuestion;

        const botMessage = document.createElement("p");
        botMessage.textContent = "Assistant: " + answer;

        messages.append(userMessage, botMessage);
        input.value = "";
    });
}


// ==========================================
// 4. SYSTEM HEALTH API
// ==========================================
async function updateSystemHealth() {
    const databaseEl = document.getElementById("database-status");
    const serverEl = document.getElementById("server-status");
    const responseCurrentEl =
    document.getElementById("response-current");

if (responseCurrentEl) {
    responseCurrentEl.textContent =
        data.response_ms !== undefined
            ? data.response_ms + " ms"
            : "Unavailable";
}
    const appEl = document.getElementById("application-status");
    const messageEl = document.getElementById("health-message");
    const healingEl = document.getElementById("self-healing-status");
    const checkedEl = document.getElementById("last-health-check");

    try {
        const response = await fetch("/api/health", {
            cache: "no-store",
            credentials: "same-origin"
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.message || "Health check failed");
        }

        if (serverEl) {
            serverEl.textContent =
                data.server === "online" ? "Online" : "Offline";
            serverEl.style.color =
                data.server === "online" ? "green" : "red";
        }

        if (databaseEl) {
            const online =
                data.database === "online" ||
                data.database === "connected";

            databaseEl.textContent = online ? "Online" : "Offline";
            databaseEl.style.color = online ? "green" : "red";
        }

        if (appEl) {
            appEl.textContent = data.application || "Unknown";
            appEl.style.color =
                data.application === "healthy" ? "green" : "red";
        }

        if (messageEl) {
            messageEl.textContent =
                data.message || "Health check completed.";
        }

        if (healingEl) {
            healingEl.textContent = data.healthy
                ? "Self-Healing: Monitoring"
                : "Self-Healing: Issue Detected";

            healingEl.style.color = data.healthy ? "green" : "red";
        }

    } catch (error) {
        console.error("Health check failed:", error);

        if (serverEl) {
            serverEl.textContent = "Unavailable";
            serverEl.style.color = "red";
        }

        if (databaseEl) {
            databaseEl.textContent = "Unknown";
            databaseEl.style.color = "gray";
        }

        if (appEl) {
            appEl.textContent = "Unavailable";
            appEl.style.color = "red";
        }

        if (messageEl) {
            messageEl.textContent =
                "Unable to check system health. Check Flask and the database.";
        }

        if (healingEl) {
            healingEl.textContent = "Self-Healing: Check Required";
            healingEl.style.color = "red";
        }
    }

    if (checkedEl) {
        checkedEl.textContent =
            "Last checked: " + new Date().toLocaleTimeString();
    }
}

updateSystemHealth();
setInterval(updateSystemHealth, 10000);

const refreshHealthButton = document.getElementById("refresh-health");

if (refreshHealthButton) {
    refreshHealthButton.addEventListener("click", updateSystemHealth);
}


// ==========================================
// 5. ERROR LAB
// ==========================================
const errorStatus = document.getElementById("error-status");
const errorDetails = document.getElementById("error-details");
const recoveryAction = document.getElementById("recovery-action");
const errorType = document.getElementById("error-type");
const generateButton = document.getElementById("generate-error");
const fixButton = document.getElementById("fix-error");

if (generateButton) {
    generateButton.addEventListener("click", async function () {
        generateButton.disabled = true;

        if (errorStatus) {
            errorStatus.textContent = "Generating controlled test...";
        }

        try {
            const response = await fetch("/api/error-lab/generate", {
                method: "POST",
                credentials: "same-origin",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    type: errorType ? errorType.value : "service"
                })
            });

            if (response.redirected) {
                throw new Error("Login required. Sign in as administrator.");
            }

            const data = await response.json();

            if (!response.ok || !data.success) {
                throw new Error(data.message || "Test failed");
            }

            if (errorStatus) {
                errorStatus.textContent =
                    `${data.status || "Test completed"} | ` +
                    `Detection: ${data.detection_ms ?? "—"} ms | ` +
                    `Recovery: ${data.recovery_ms ?? "—"} ms`;
            }

            if (errorDetails) {
                errorDetails.textContent =
                    data.details || data.failure || data.message || "";
            }

            if (recoveryAction) {
                recoveryAction.textContent =
                    JSON.stringify(data.recovery || {}, null, 2) +
                    "\n" + (data.message || "");
            }

            await loadIncidentTimeline();
            await updateSystemHealth();

        } catch (error) {
            if (errorStatus) {
                errorStatus.textContent = "Test failed: " + error.message;
            }

            if (errorDetails) {
                errorDetails.textContent =
                    "Check administrator login and the Flask terminal.";
            }
        } finally {
            generateButton.disabled = false;
        }
    });
}

if (fixButton) {
    fixButton.addEventListener("click", async function () {
        fixButton.disabled = true;

        try {
            const response = await fetch("/api/error-lab/fix", {
                method: "POST",
                credentials: "same-origin"
            });

            if (response.redirected) {
                throw new Error("Login required. Sign in as administrator.");
            }

            const data = await response.json();

            if (errorStatus) {
                errorStatus.textContent =
                    data.status || data.message || "Recovery request completed";
            }

            if (recoveryAction) {
                recoveryAction.textContent = data.message || "";
            }

            await loadIncidentTimeline();
            await updateSystemHealth();

        } catch (error) {
            if (errorStatus) {
                errorStatus.textContent = error.message;
            }
        } finally {
            fixButton.disabled = false;
        }
    });
}


// ==========================================
// 6. INCIDENT TIMELINE
// ==========================================
async function loadIncidentTimeline() {
    try {
        const response = await fetch("/api/incidents", {
            credentials: "same-origin",
            cache: "no-store"
        });

        if (!response.ok) {
            throw new Error("Could not load incidents");
        }

        const incidents = await response.json();

        // Update this selector if your HTML table uses a different ID.
        const tableBody = document.querySelector("#incident-table tbody");

        if (!tableBody) {
            console.warn(
                "Timeline table not found. Check the table ID in dashboard.html."
            );
            return;
        }

        tableBody.replaceChildren();

        if (!Array.isArray(incidents) || incidents.length === 0) {
            const row = document.createElement("tr");
            const cell = document.createElement("td");

            cell.colSpan = 4;
            cell.textContent = "No incidents recorded yet.";

            row.appendChild(cell);
            tableBody.appendChild(row);
            return;
        }

        incidents.forEach(function (incident) {
            const row = document.createElement("tr");

            const values = [
                incident.issue || incident.failure || "Unknown incident",
                incident.status || "Detected",
                incident.detection_ms ?? "—",
                incident.recovery_ms ?? "—"
            ];

            values.forEach(function (value) {
                const cell = document.createElement("td");
                cell.textContent = String(value);
                row.appendChild(cell);
            });

            tableBody.appendChild(row);
        });

    } catch (error) {
        console.error("Incident timeline error:", error);
    }
}

loadIncidentTimeline();
setInterval(loadIncidentTimeline, 5000);
