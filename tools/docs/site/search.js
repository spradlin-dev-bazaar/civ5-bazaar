(function () {
	var root = document.body.getAttribute("data-root") || "";
	var index = document.body.getAttribute("data-index");
	var input = document.querySelector(".search input");
	var list = document.querySelector(".search .results");
	var loading = false;
	var active = -1;

	// The index is a script, not JSON fetched by the page, so that search also works on pages opened from disk.
	function load(then) {
		if (window.BAZAAR_INDEX) return then();
		if (loading) return;
		loading = true;
		var script = document.createElement("script");
		script.src = root + index;
		script.onload = then;
		script.onerror = function () {
			list.innerHTML = "";
			var li = document.createElement("li");
			li.className = "message";
			li.textContent = "Search could not load.";
			list.appendChild(li);
		};
		document.head.appendChild(script);
	}

	function rank(label, query) {
		var lower = label.toLowerCase();
		var at = lower.indexOf(query);
		if (at < 0) return -1;
		var name = lower.split("(")[0].trim();
		var scope = name.lastIndexOf("::");
		var leaf = scope < 0 ? name : name.slice(scope + 2);
		if (leaf === query) return 0;
		if (leaf.indexOf(query) === 0) return 1;
		if (at === 0) return 2;
		return 3;
	}

	function show() {
		var query = input.value.trim().toLowerCase();
		list.innerHTML = "";
		active = -1;
		if (!query || !window.BAZAAR_INDEX) return;
		var hits = [];
		var rows = window.BAZAAR_INDEX;
		for (var i = 0; i < rows.length; i++) {
			var r = rank(rows[i][0], query);
			if (r >= 0) hits.push([r, rows[i][0].length, rows[i]]);
		}
		hits.sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; });
		hits.slice(0, 50).forEach(function (hit) {
			var a = document.createElement("a");
			a.href = root + hit[2][1];
			a.textContent = hit[2][0];
			var li = document.createElement("li");
			li.appendChild(a);
			list.appendChild(li);
		});
	}

	function move(step) {
		var links = list.querySelectorAll("a");
		if (!links.length) return;
		if (active >= 0) links[active].classList.remove("active");
		active = (active + step + links.length) % links.length;
		links[active].classList.add("active");
		links[active].scrollIntoView({ block: "nearest" });
	}

	input.addEventListener("focus", function () { load(show); });
	input.addEventListener("input", function () { load(show); });
	input.addEventListener("keydown", function (e) {
		if (e.key === "ArrowDown") { move(1); e.preventDefault(); }
		else if (e.key === "ArrowUp") { move(-1); e.preventDefault(); }
		else if (e.key === "Enter") {
			var links = list.querySelectorAll("a");
			if (links.length) window.location.href = links[Math.max(active, 0)].href;
		} else if (e.key === "Escape") { list.innerHTML = ""; input.blur(); }
	});
	document.addEventListener("click", function (e) {
		if (!e.target.closest(".search")) list.innerHTML = "";
	});
})();
