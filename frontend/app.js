
const buildBtn = document.getElementById("buildBtn");
const promptInput = document.getElementById("prompt");
const activityLog = document.getElementById("activityLog");
const resultBox = document.getElementById("resultBox");

function setActivity(message, type = "idle") {
    const entry = document.createElement("div");
    entry.className = `log-entry ${type}`;

    const dot = document.createElement("span");
    dot.className = "dot";

    const text = document.createElement("span");
    text.textContent = message;

    entry.appendChild(dot);
    entry.appendChild(text);

    activityLog.prepend(entry);
}

function setResult(message, state = "default") {
    resultBox.className = `result-box ${state}`;
    resultBox.replaceChildren();

    const paragraph = document.createElement("p");
    paragraph.textContent = message;

    resultBox.appendChild(paragraph);
}

function clearActivities() {
    activityLog.replaceChildren();
}

async function parseResponse(response) {
    const text = await response.text();

    if (!text.trim()) {
        throw new Error(
            `Backend returned an empty response (${response.status}).`
        );
    }

    try {
        return JSON.parse(text);
    } catch {
        throw new Error(
            `Backend returned invalid JSON (${response.status}): ${text.slice(
                0,
                300
            )}`
        );
    }
}

function showSuccess(job) {
    resultBox.className = "result-box success";
    resultBox.replaceChildren();

    const heading = document.createElement("p");
    heading.textContent = "Website created and verified successfully.";
    resultBox.appendChild(heading);

    const project = document.createElement("p");
    project.textContent = `Project: ${job.project_name || "Unknown"}`;
    resultBox.appendChild(project);

    const filesHeading = document.createElement("p");
    filesHeading.textContent = "Generated files:";
    resultBox.appendChild(filesHeading);

    const fileList = document.createElement("ul");

    for (const file of job.files || []) {
        const item = document.createElement("li");
        item.textContent = file;
        fileList.appendChild(item);
    }

    resultBox.appendChild(fileList);

    if (job.project_name) {
        const openButton = document.createElement("button");

        openButton.type = "button";
        openButton.textContent = "Open Website";

        openButton.addEventListener("click", () => {
            const projectName = encodeURIComponent(job.project_name);

            window.open(
                `/sites/${projectName}/`,
                "_blank",
                "noopener"
            );
        });

        resultBox.appendChild(openButton);
    }
}

async function waitForJob(jobId) {
    let eventOffset = 0;

    while (true) {
        const response = await fetch(
            `/portfolio/${encodeURIComponent(jobId)}`,
            {
                method: "GET",
                headers: {
                    Accept: "application/json"
                },
                cache: "no-store"
            }
        );

        const job = await parseResponse(response);

        if (!response.ok) {
            throw new Error(
                job.detail ||
                    `Could not read build status (${response.status}).`
            );
        }

        const events = Array.isArray(job.events)
            ? job.events
            : [];

        for (const event of events.slice(eventOffset)) {
            setActivity(
                event.message || "Agent is working...",
                event.state === "failed" ? "error" : "idle"
            );
        }

        eventOffset = events.length;

        if (job.status === "completed") {
            showSuccess(job);
            return;
        }

        if (job.status === "failed") {
            throw new Error(
                job.error || "Website generation failed."
            );
        }

        await new Promise((resolve) => {
            setTimeout(resolve, 700);
        });
    }
}

buildBtn.addEventListener("click", async () => {
    const prompt = promptInput.value.trim();

    if (!prompt) {
        setActivity(
            "Please describe the website you want to build.",
            "error"
        );

        setResult(
            "Please enter a website prompt before building.",
            "error"
        );

        return;
    }

    buildBtn.disabled = true;

    clearActivities();

    setActivity(
        "Submitting website request to the backend...",
        "loading"
    );

    setResult(
        "Waiting for the backend to start the build..."
    );

    try {
        // Start website generation
        const response = await fetch("/portfolio", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                Accept: "application/json"
            },
            body: JSON.stringify({
                prompt: prompt
            })
        });

        const payload = await parseResponse(response);

        if (!response.ok) {
            throw new Error(
                payload.detail ||
                    `Request failed (${response.status}).`
            );
        }

        if (!payload.job_id) {
            throw new Error(
                "Backend response did not contain a job_id."
            );
        }

        setActivity(
            "Build job started. AI agent is working...",
            "loading"
        );

        await waitForJob(payload.job_id);

    } catch (error) {
        console.error("Website build error:", error);

        const message =
            error instanceof Error
                ? error.message
                : "Website generation failed.";

        setActivity(message, "error");
        setResult(message, "error");

    } finally {
        buildBtn.disabled = false;
    }
});
