async function send() {
    const msg = document.getElementById("msg").value;

    const res = await fetch("/api/orchestrate", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message: msg})
    });

    const data = await res.json();
    document.getElementById("out").textContent = JSON.stringify(data, null, 2);
}
