//#region node_modules/@lit/reactive-element/css-tag.js
var e = globalThis, t = e.ShadowRoot && (e.ShadyCSS === void 0 || e.ShadyCSS.nativeShadow) && "adoptedStyleSheets" in Document.prototype && "replace" in CSSStyleSheet.prototype, n = Symbol(), r = /* @__PURE__ */ new WeakMap(), i = class {
	constructor(e, t, r) {
		if (this._$cssResult$ = !0, r !== n) throw Error("CSSResult is not constructable. Use `unsafeCSS` or `css` instead.");
		this.cssText = e, this.t = t;
	}
	get styleSheet() {
		let e = this.o, n = this.t;
		if (t && e === void 0) {
			let t = n !== void 0 && n.length === 1;
			t && (e = r.get(n)), e === void 0 && ((this.o = e = new CSSStyleSheet()).replaceSync(this.cssText), t && r.set(n, e));
		}
		return e;
	}
	toString() {
		return this.cssText;
	}
}, a = (e) => new i(typeof e == "string" ? e : e + "", void 0, n), o = (e, ...t) => new i(e.length === 1 ? e[0] : t.reduce((t, n, r) => t + ((e) => {
	if (!0 === e._$cssResult$) return e.cssText;
	if (typeof e == "number") return e;
	throw Error("Value passed to 'css' function must be a 'css' function result: " + e + ". Use 'unsafeCSS' to pass non-literal values, but take care to ensure page security.");
})(n) + e[r + 1], e[0]), e, n), s = (n, r) => {
	if (t) n.adoptedStyleSheets = r.map((e) => e instanceof CSSStyleSheet ? e : e.styleSheet);
	else for (let t of r) {
		let r = document.createElement("style"), i = e.litNonce;
		i !== void 0 && r.setAttribute("nonce", i), r.textContent = t.cssText, n.appendChild(r);
	}
}, c = t ? (e) => e : (e) => e instanceof CSSStyleSheet ? ((e) => {
	let t = "";
	for (let n of e.cssRules) t += n.cssText;
	return a(t);
})(e) : e, { is: l, defineProperty: u, getOwnPropertyDescriptor: d, getOwnPropertyNames: ee, getOwnPropertySymbols: te, getPrototypeOf: ne } = Object, f = globalThis, re = f.trustedTypes, ie = re ? re.emptyScript : "", ae = f.reactiveElementPolyfillSupport, p = (e, t) => e, m = {
	toAttribute(e, t) {
		switch (t) {
			case Boolean:
				e = e ? ie : null;
				break;
			case Object:
			case Array: e = e == null ? e : JSON.stringify(e);
		}
		return e;
	},
	fromAttribute(e, t) {
		let n = e;
		switch (t) {
			case Boolean:
				n = e !== null;
				break;
			case Number:
				n = e === null ? null : Number(e);
				break;
			case Object:
			case Array: try {
				n = JSON.parse(e);
			} catch {
				n = null;
			}
		}
		return n;
	}
}, h = (e, t) => !l(e, t), g = {
	attribute: !0,
	type: String,
	converter: m,
	reflect: !1,
	useDefault: !1,
	hasChanged: h
};
Symbol.metadata ??= Symbol("metadata"), f.litPropertyMetadata ??= /* @__PURE__ */ new WeakMap();
var _ = class extends HTMLElement {
	static addInitializer(e) {
		this._$Ei(), (this.l ??= []).push(e);
	}
	static get observedAttributes() {
		return this.finalize(), this._$Eh && [...this._$Eh.keys()];
	}
	static createProperty(e, t = g) {
		if (t.state && (t.attribute = !1), this._$Ei(), this.prototype.hasOwnProperty(e) && ((t = Object.create(t)).wrapped = !0), this.elementProperties.set(e, t), !t.noAccessor) {
			let n = Symbol(), r = this.getPropertyDescriptor(e, n, t);
			r !== void 0 && u(this.prototype, e, r);
		}
	}
	static getPropertyDescriptor(e, t, n) {
		let { get: r, set: i } = d(this.prototype, e) ?? {
			get() {
				return this[t];
			},
			set(e) {
				this[t] = e;
			}
		};
		return {
			get: r,
			set(t) {
				let a = r?.call(this);
				i?.call(this, t), this.requestUpdate(e, a, n);
			},
			configurable: !0,
			enumerable: !0
		};
	}
	static getPropertyOptions(e) {
		return this.elementProperties.get(e) ?? g;
	}
	static _$Ei() {
		if (this.hasOwnProperty(p("elementProperties"))) return;
		let e = ne(this);
		e.finalize(), e.l !== void 0 && (this.l = [...e.l]), this.elementProperties = new Map(e.elementProperties);
	}
	static finalize() {
		if (this.hasOwnProperty(p("finalized"))) return;
		if (this.finalized = !0, this._$Ei(), this.hasOwnProperty(p("properties"))) {
			let e = this.properties, t = [...ee(e), ...te(e)];
			for (let n of t) this.createProperty(n, e[n]);
		}
		let e = this[Symbol.metadata];
		if (e !== null) {
			let t = litPropertyMetadata.get(e);
			if (t !== void 0) for (let [e, n] of t) this.elementProperties.set(e, n);
		}
		this._$Eh = /* @__PURE__ */ new Map();
		for (let [e, t] of this.elementProperties) {
			let n = this._$Eu(e, t);
			n !== void 0 && this._$Eh.set(n, e);
		}
		this.elementStyles = this.finalizeStyles(this.styles);
	}
	static finalizeStyles(e) {
		let t = [];
		if (Array.isArray(e)) {
			let n = new Set(e.flat(1 / 0).reverse());
			for (let e of n) t.unshift(c(e));
		} else e !== void 0 && t.push(c(e));
		return t;
	}
	static _$Eu(e, t) {
		let n = t.attribute;
		return !1 === n ? void 0 : typeof n == "string" ? n : typeof e == "string" ? e.toLowerCase() : void 0;
	}
	constructor() {
		super(), this._$Ep = void 0, this.isUpdatePending = !1, this.hasUpdated = !1, this._$Em = null, this._$Ev();
	}
	_$Ev() {
		this._$ES = new Promise((e) => this.enableUpdating = e), this._$AL = /* @__PURE__ */ new Map(), this._$E_(), this.requestUpdate(), this.constructor.l?.forEach((e) => e(this));
	}
	addController(e) {
		(this._$EO ??= /* @__PURE__ */ new Set()).add(e), this.renderRoot !== void 0 && this.isConnected && e.hostConnected?.();
	}
	removeController(e) {
		this._$EO?.delete(e);
	}
	_$E_() {
		let e = /* @__PURE__ */ new Map(), t = this.constructor.elementProperties;
		for (let n of t.keys()) this.hasOwnProperty(n) && (e.set(n, this[n]), delete this[n]);
		e.size > 0 && (this._$Ep = e);
	}
	createRenderRoot() {
		let e = this.shadowRoot ?? this.attachShadow(this.constructor.shadowRootOptions);
		return s(e, this.constructor.elementStyles), e;
	}
	connectedCallback() {
		this.renderRoot ??= this.createRenderRoot(), this.enableUpdating(!0), this._$EO?.forEach((e) => e.hostConnected?.());
	}
	enableUpdating(e) {}
	disconnectedCallback() {
		this._$EO?.forEach((e) => e.hostDisconnected?.());
	}
	attributeChangedCallback(e, t, n) {
		this._$AK(e, n);
	}
	_$ET(e, t) {
		let n = this.constructor.elementProperties.get(e), r = this.constructor._$Eu(e, n);
		if (r !== void 0 && !0 === n.reflect) {
			let i = (n.converter?.toAttribute === void 0 ? m : n.converter).toAttribute(t, n.type);
			this._$Em = e, i == null ? this.removeAttribute(r) : this.setAttribute(r, i), this._$Em = null;
		}
	}
	_$AK(e, t) {
		let n = this.constructor, r = n._$Eh.get(e);
		if (r !== void 0 && this._$Em !== r) {
			let e = n.getPropertyOptions(r), i = typeof e.converter == "function" ? { fromAttribute: e.converter } : e.converter?.fromAttribute === void 0 ? m : e.converter;
			this._$Em = r;
			let a = i.fromAttribute(t, e.type);
			this[r] = a ?? this._$Ej?.get(r) ?? a, this._$Em = null;
		}
	}
	requestUpdate(e, t, n, r = !1, i) {
		if (e !== void 0) {
			let a = this.constructor;
			if (!1 === r && (i = this[e]), n ??= a.getPropertyOptions(e), !((n.hasChanged ?? h)(i, t) || n.useDefault && n.reflect && i === this._$Ej?.get(e) && !this.hasAttribute(a._$Eu(e, n)))) return;
			this.C(e, t, n);
		}
		!1 === this.isUpdatePending && (this._$ES = this._$EP());
	}
	C(e, t, { useDefault: n, reflect: r, wrapped: i }, a) {
		n && !(this._$Ej ??= /* @__PURE__ */ new Map()).has(e) && (this._$Ej.set(e, a ?? t ?? this[e]), !0 !== i || a !== void 0) || (this._$AL.has(e) || (this.hasUpdated || n || (t = void 0), this._$AL.set(e, t)), !0 === r && this._$Em !== e && (this._$Eq ??= /* @__PURE__ */ new Set()).add(e));
	}
	async _$EP() {
		this.isUpdatePending = !0;
		try {
			await this._$ES;
		} catch (e) {
			Promise.reject(e);
		}
		let e = this.scheduleUpdate();
		return e != null && await e, !this.isUpdatePending;
	}
	scheduleUpdate() {
		return this.performUpdate();
	}
	performUpdate() {
		if (!this.isUpdatePending) return;
		if (!this.hasUpdated) {
			if (this.renderRoot ??= this.createRenderRoot(), this._$Ep) {
				for (let [e, t] of this._$Ep) this[e] = t;
				this._$Ep = void 0;
			}
			let e = this.constructor.elementProperties;
			if (e.size > 0) for (let [t, n] of e) {
				let { wrapped: e } = n, r = this[t];
				!0 !== e || this._$AL.has(t) || r === void 0 || this.C(t, void 0, n, r);
			}
		}
		let e = !1, t = this._$AL;
		try {
			e = this.shouldUpdate(t), e ? (this.willUpdate(t), this._$EO?.forEach((e) => e.hostUpdate?.()), this.update(t)) : this._$EM();
		} catch (t) {
			throw e = !1, this._$EM(), t;
		}
		e && this._$AE(t);
	}
	willUpdate(e) {}
	_$AE(e) {
		this._$EO?.forEach((e) => e.hostUpdated?.()), this.hasUpdated || (this.hasUpdated = !0, this.firstUpdated(e)), this.updated(e);
	}
	_$EM() {
		this._$AL = /* @__PURE__ */ new Map(), this.isUpdatePending = !1;
	}
	get updateComplete() {
		return this.getUpdateComplete();
	}
	getUpdateComplete() {
		return this._$ES;
	}
	shouldUpdate(e) {
		return !0;
	}
	update(e) {
		this._$Eq &&= this._$Eq.forEach((e) => this._$ET(e, this[e])), this._$EM();
	}
	updated(e) {}
	firstUpdated(e) {}
};
_.elementStyles = [], _.shadowRootOptions = { mode: "open" }, _[p("elementProperties")] = /* @__PURE__ */ new Map(), _[p("finalized")] = /* @__PURE__ */ new Map(), ae?.({ ReactiveElement: _ }), (f.reactiveElementVersions ??= []).push("2.1.2");
//#endregion
//#region node_modules/lit-html/lit-html.js
var v = globalThis, oe = (e) => e, y = v.trustedTypes, se = y ? y.createPolicy("lit-html", { createHTML: (e) => e }) : void 0, ce = "$lit$", b = `lit$${Math.random().toFixed(9).slice(2)}$`, x = "?" + b, le = `<${x}>`, S = document, C = () => S.createComment(""), w = (e) => e === null || typeof e != "object" && typeof e != "function", T = Array.isArray, ue = (e) => T(e) || typeof e?.[Symbol.iterator] == "function", E = "[ 	\n\f\r]", D = /<(?:(!--|\/[^a-zA-Z])|(\/?[a-zA-Z][^>\s]*)|(\/?$))/g, de = /-->/g, fe = />/g, O = RegExp(`>|${E}(?:([^\\s"'>=/]+)(${E}*=${E}*(?:[^ \t\n\f\r"'\`<>=]|("|')|))|$)`, "g"), pe = /'/g, me = /"/g, he = /^(?:script|style|textarea|title)$/i, k = ((e) => (t, ...n) => ({
	_$litType$: e,
	strings: t,
	values: n
}))(1), A = Symbol.for("lit-noChange"), j = Symbol.for("lit-nothing"), M = /* @__PURE__ */ new WeakMap(), N = S.createTreeWalker(S, 129);
function P(e, t) {
	if (!T(e) || !e.hasOwnProperty("raw")) throw Error("invalid template strings array");
	return se === void 0 ? t : se.createHTML(t);
}
var ge = (e, t) => {
	let n = e.length - 1, r = [], i, a = t === 2 ? "<svg>" : t === 3 ? "<math>" : "", o = D;
	for (let t = 0; t < n; t++) {
		let n = e[t], s, c, l = -1, u = 0;
		for (; u < n.length && (o.lastIndex = u, c = o.exec(n), c !== null);) u = o.lastIndex, o === D ? c[1] === "!--" ? o = de : c[1] === void 0 ? c[2] === void 0 ? c[3] !== void 0 && (o = O) : (he.test(c[2]) && (i = RegExp("</" + c[2], "g")), o = O) : o = fe : o === O ? c[0] === ">" ? (o = i ?? D, l = -1) : c[1] === void 0 ? l = -2 : (l = o.lastIndex - c[2].length, s = c[1], o = c[3] === void 0 ? O : c[3] === "\"" ? me : pe) : o === me || o === pe ? o = O : o === de || o === fe ? o = D : (o = O, i = void 0);
		let d = o === O && e[t + 1].startsWith("/>") ? " " : "";
		a += o === D ? n + le : l >= 0 ? (r.push(s), n.slice(0, l) + ce + n.slice(l) + b + d) : n + b + (l === -2 ? t : d);
	}
	return [P(e, a + (e[n] || "<?>") + (t === 2 ? "</svg>" : t === 3 ? "</math>" : "")), r];
}, F = class e {
	constructor({ strings: t, _$litType$: n }, r) {
		let i;
		this.parts = [];
		let a = 0, o = 0, s = t.length - 1, c = this.parts, [l, u] = ge(t, n);
		if (this.el = e.createElement(l, r), N.currentNode = this.el.content, n === 2 || n === 3) {
			let e = this.el.content.firstChild;
			e.replaceWith(...e.childNodes);
		}
		for (; (i = N.nextNode()) !== null && c.length < s;) {
			if (i.nodeType === 1) {
				if (i.hasAttributes()) for (let e of i.getAttributeNames()) if (e.endsWith(ce)) {
					let t = u[o++], n = i.getAttribute(e).split(b), r = /([.?@])?(.*)/.exec(t);
					c.push({
						type: 1,
						index: a,
						name: r[2],
						strings: n,
						ctor: r[1] === "." ? ve : r[1] === "?" ? ye : r[1] === "@" ? be : R
					}), i.removeAttribute(e);
				} else e.startsWith(b) && (c.push({
					type: 6,
					index: a
				}), i.removeAttribute(e));
				if (he.test(i.tagName)) {
					let e = i.textContent.split(b), t = e.length - 1;
					if (t > 0) {
						i.textContent = y ? y.emptyScript : "";
						for (let n = 0; n < t; n++) i.append(e[n], C()), N.nextNode(), c.push({
							type: 2,
							index: ++a
						});
						i.append(e[t], C());
					}
				}
			} else if (i.nodeType === 8) {
				if (i.data === x) c.push({
					type: 2,
					index: a
				});
				else {
					let e = -1;
					for (; (e = i.data.indexOf(b, e + 1)) !== -1;) c.push({
						type: 7,
						index: a
					}), e += b.length - 1;
				}
			}
			a++;
		}
	}
	static createElement(e, t) {
		let n = S.createElement("template");
		return n.innerHTML = e, n;
	}
};
function I(e, t, n = e, r) {
	if (t === A) return t;
	let i = r === void 0 ? n._$Cl : n._$Co?.[r], a = w(t) ? void 0 : t._$litDirective$;
	return i?.constructor !== a && (i?._$AO?.(!1), a === void 0 ? i = void 0 : (i = new a(e), i._$AT(e, n, r)), r === void 0 ? n._$Cl = i : (n._$Co ??= [])[r] = i), i !== void 0 && (t = I(e, i._$AS(e, t.values), i, r)), t;
}
var _e = class {
	constructor(e, t) {
		this._$AV = [], this._$AN = void 0, this._$AD = e, this._$AM = t;
	}
	get parentNode() {
		return this._$AM.parentNode;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	u(e) {
		let { el: { content: t }, parts: n } = this._$AD, r = (e?.creationScope ?? S).importNode(t, !0);
		N.currentNode = r;
		let i = N.nextNode(), a = 0, o = 0, s = n[0];
		for (; s !== void 0;) {
			if (a === s.index) {
				let t;
				s.type === 2 ? t = new L(i, i.nextSibling, this, e) : s.type === 1 ? t = new s.ctor(i, s.name, s.strings, this, e) : s.type === 6 && (t = new xe(i, this, e)), this._$AV.push(t), s = n[++o];
			}
			a !== s?.index && (i = N.nextNode(), a++);
		}
		return N.currentNode = S, r;
	}
	p(e) {
		let t = 0;
		for (let n of this._$AV) n !== void 0 && (n.strings === void 0 ? n._$AI(e[t]) : (n._$AI(e, n, t), t += n.strings.length - 2)), t++;
	}
}, L = class e {
	get _$AU() {
		return this._$AM?._$AU ?? this._$Cv;
	}
	constructor(e, t, n, r) {
		this.type = 2, this._$AH = j, this._$AN = void 0, this._$AA = e, this._$AB = t, this._$AM = n, this.options = r, this._$Cv = r?.isConnected ?? !0;
	}
	get parentNode() {
		let e = this._$AA.parentNode, t = this._$AM;
		return t !== void 0 && e?.nodeType === 11 && (e = t.parentNode), e;
	}
	get startNode() {
		return this._$AA;
	}
	get endNode() {
		return this._$AB;
	}
	_$AI(e, t = this) {
		e = I(this, e, t), w(e) ? e === j || e == null || e === "" ? (this._$AH !== j && this._$AR(), this._$AH = j) : e !== this._$AH && e !== A && this._(e) : e._$litType$ === void 0 ? e.nodeType === void 0 ? ue(e) ? this.k(e) : this._(e) : this.T(e) : this.$(e);
	}
	O(e) {
		return this._$AA.parentNode.insertBefore(e, this._$AB);
	}
	T(e) {
		this._$AH !== e && (this._$AR(), this._$AH = this.O(e));
	}
	_(e) {
		this._$AH !== j && w(this._$AH) ? this._$AA.nextSibling.data = e : this.T(S.createTextNode(e)), this._$AH = e;
	}
	$(e) {
		let { values: t, _$litType$: n } = e, r = typeof n == "number" ? this._$AC(e) : (n.el === void 0 && (n.el = F.createElement(P(n.h, n.h[0]), this.options)), n);
		if (this._$AH?._$AD === r) this._$AH.p(t);
		else {
			let e = new _e(r, this), n = e.u(this.options);
			e.p(t), this.T(n), this._$AH = e;
		}
	}
	_$AC(e) {
		let t = M.get(e.strings);
		return t === void 0 && M.set(e.strings, t = new F(e)), t;
	}
	k(t) {
		T(this._$AH) || (this._$AH = [], this._$AR());
		let n = this._$AH, r, i = 0;
		for (let a of t) i === n.length ? n.push(r = new e(this.O(C()), this.O(C()), this, this.options)) : r = n[i], r._$AI(a), i++;
		i < n.length && (this._$AR(r && r._$AB.nextSibling, i), n.length = i);
	}
	_$AR(e = this._$AA.nextSibling, t) {
		for (this._$AP?.(!1, !0, t); e !== this._$AB;) {
			let t = oe(e).nextSibling;
			oe(e).remove(), e = t;
		}
	}
	setConnected(e) {
		this._$AM === void 0 && (this._$Cv = e, this._$AP?.(e));
	}
}, R = class {
	get tagName() {
		return this.element.tagName;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	constructor(e, t, n, r, i) {
		this.type = 1, this._$AH = j, this._$AN = void 0, this.element = e, this.name = t, this._$AM = r, this.options = i, n.length > 2 || n[0] !== "" || n[1] !== "" ? (this._$AH = Array(n.length - 1).fill(/* @__PURE__ */ new String()), this.strings = n) : this._$AH = j;
	}
	_$AI(e, t = this, n, r) {
		let i = this.strings, a = !1;
		if (i === void 0) e = I(this, e, t, 0), a = !w(e) || e !== this._$AH && e !== A, a && (this._$AH = e);
		else {
			let r = e, o, s;
			for (e = i[0], o = 0; o < i.length - 1; o++) s = I(this, r[n + o], t, o), s === A && (s = this._$AH[o]), a ||= !w(s) || s !== this._$AH[o], s === j ? e = j : e !== j && (e += (s ?? "") + i[o + 1]), this._$AH[o] = s;
		}
		a && !r && this.j(e);
	}
	j(e) {
		e === j ? this.element.removeAttribute(this.name) : this.element.setAttribute(this.name, e ?? "");
	}
}, ve = class extends R {
	constructor() {
		super(...arguments), this.type = 3;
	}
	j(e) {
		this.element[this.name] = e === j ? void 0 : e;
	}
}, ye = class extends R {
	constructor() {
		super(...arguments), this.type = 4;
	}
	j(e) {
		this.element.toggleAttribute(this.name, !!e && e !== j);
	}
}, be = class extends R {
	constructor(e, t, n, r, i) {
		super(e, t, n, r, i), this.type = 5;
	}
	_$AI(e, t = this) {
		if ((e = I(this, e, t, 0) ?? j) === A) return;
		let n = this._$AH, r = e === j && n !== j || e.capture !== n.capture || e.once !== n.once || e.passive !== n.passive, i = e !== j && (n === j || r);
		r && this.element.removeEventListener(this.name, this, n), i && this.element.addEventListener(this.name, this, e), this._$AH = e;
	}
	handleEvent(e) {
		typeof this._$AH == "function" ? this._$AH.call(this.options?.host ?? this.element, e) : this._$AH.handleEvent(e);
	}
}, xe = class {
	constructor(e, t, n) {
		this.element = e, this.type = 6, this._$AN = void 0, this._$AM = t, this.options = n;
	}
	get _$AU() {
		return this._$AM._$AU;
	}
	_$AI(e) {
		I(this, e);
	}
}, Se = v.litHtmlPolyfillSupport;
Se?.(F, L), (v.litHtmlVersions ??= []).push("3.3.3");
var Ce = (e, t, n) => {
	let r = n?.renderBefore ?? t, i = r._$litPart$;
	if (i === void 0) {
		let e = n?.renderBefore ?? null;
		r._$litPart$ = i = new L(t.insertBefore(C(), e), e, void 0, n ?? {});
	}
	return i._$AI(e), i;
}, z = globalThis, B = class extends _ {
	constructor() {
		super(...arguments), this.renderOptions = { host: this }, this._$Do = void 0;
	}
	createRenderRoot() {
		let e = super.createRenderRoot();
		return this.renderOptions.renderBefore ??= e.firstChild, e;
	}
	update(e) {
		let t = this.render();
		this.hasUpdated || (this.renderOptions.isConnected = this.isConnected), super.update(e), this._$Do = Ce(t, this.renderRoot, this.renderOptions);
	}
	connectedCallback() {
		super.connectedCallback(), this._$Do?.setConnected(!0);
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this._$Do?.setConnected(!1);
	}
	render() {
		return A;
	}
};
B._$litElement$ = !0, B.finalized = !0, z.litElementHydrateSupport?.({ LitElement: B });
var we = z.litElementPolyfillSupport;
we?.({ LitElement: B }), (z.litElementVersions ??= []).push("4.2.2");
//#endregion
//#region src/elements/styles.ts
var V = o`
  :host {
    --rw-text: var(--primary-text-color, #212121);
    --rw-dim: var(--secondary-text-color, #727272);
    --rw-accent: var(--primary-color, #03a9f4);
    --rw-surface: var(--card-background-color, var(--ha-card-background, #fff));
    --rw-line: var(--divider-color, #e0e0e0);
    --rw-alert: var(--error-color, #db4437);
    --rw-warn: var(--warning-color, #ffa600);
    --rw-radius: var(--ha-card-border-radius, 12px);

    display: block;
    color: var(--rw-text);
    font-family: var(--paper-font-body1_-_font-family, Roboto, system-ui, sans-serif);
    font-size: 18px;
    line-height: 1.45;
    box-sizing: border-box;
  }

  *,
  *::before,
  *::after {
    box-sizing: inherit;
  }

  h2,
  h3 {
    margin: 0;
    font-weight: 500;
  }

  .muted {
    color: var(--rw-dim);
  }

  .row {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
  }

  .spread {
    justify-content: space-between;
  }

  /* -- controls ---------------------------------------------------------- */

  button {
    font: inherit;
    color: inherit;
    background: none;
    border: 2px solid var(--rw-line);
    border-radius: var(--rw-radius);
    padding: 12px 18px;
    min-height: 56px;
    cursor: pointer;
    touch-action: manipulation;
  }

  button:disabled {
    opacity: 0.4;
    cursor: default;
  }

  button.primary {
    background: var(--rw-accent);
    border-color: var(--rw-accent);
    color: var(--text-primary-color, #fff);
  }

  /* The two the cook actually hits, mid-recipe, without looking properly. */
  .movement {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: 12px;
    margin-top: 24px;
  }

  .movement button {
    min-height: 76px;
    font-size: 22px;
    font-weight: 500;
  }

  /* -- the step ---------------------------------------------------------- */

  .position {
    font-variant-numeric: tabular-nums;
    font-size: 15px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--rw-dim);
  }

  .step-text {
    font-size: 28px;
    line-height: 1.3;
    margin: 16px 0;
  }

  .attention {
    display: inline-block;
    border: 2px solid currentColor;
    border-radius: 999px;
    padding: 2px 12px;
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .attention.active {
    color: var(--rw-alert);
  }

  .attention.passive {
    color: var(--rw-warn);
  }

  .attention.unattended {
    color: var(--rw-accent);
  }

  .needs {
    list-style: none;
    margin: 0;
    padding: 0;
    border-top: 1px solid var(--rw-line);
  }

  .needs li {
    padding: 10px 0;
    border-bottom: 1px solid var(--rw-line);
    font-size: 20px;
  }

  .needs .state {
    display: block;
    font-size: 16px;
    color: var(--rw-dim);
  }

  /* -- the timer, and the thing that outranks it ------------------------- */

  .timing {
    margin-top: 20px;
    padding: 16px;
    border: 2px solid var(--rw-line);
    border-radius: var(--rw-radius);
  }

  .timing.awaiting {
    border-color: var(--rw-warn);
  }

  .doneness {
    font-size: 24px;
    line-height: 1.3;
  }

  .doneness .lead {
    display: block;
    font-size: 15px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--rw-warn);
  }

  .countdown {
    font-variant-numeric: tabular-nums;
    font-size: 40px;
    line-height: 1.1;
    margin-top: 8px;
  }

  .countdown.estimate {
    font-size: 30px;
    color: var(--rw-dim);
  }

  .stated {
    font-size: 17px;
    color: var(--rw-dim);
  }

  .note {
    margin-top: 12px;
    padding-left: 12px;
    border-left: 4px solid var(--rw-alert);
    font-size: 17px;
  }

  .findings {
    margin-top: 16px;
    padding-left: 12px;
    border-left: 4px solid var(--rw-warn);
    font-size: 16px;
    color: var(--rw-dim);
  }

  /* -- the picker -------------------------------------------------------- */

  .family {
    margin: 20px 0 6px;
    font-size: 15px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--rw-dim);
  }

  .recipes {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .recipes li {
    margin: 8px 0;
  }

  .recipes button {
    width: 100%;
    text-align: left;
    font-size: 20px;
    min-height: 64px;
  }

  .recipes button[aria-pressed="true"] {
    border-color: var(--rw-accent);
  }

  .batches {
    margin-top: 20px;
  }

  .batches output {
    font-variant-numeric: tabular-nums;
    font-size: 28px;
    min-width: 3ch;
    text-align: center;
  }

  .batches button {
    min-width: 64px;
    font-size: 26px;
  }

  .error {
    color: var(--rw-alert);
    margin-top: 12px;
  }
`, H, Te = class extends B {
	constructor(...e) {
		super(...e), this.index = null, this.chosen = null, this.batches = 1;
	}
	render() {
		if (!this.index) return k`<p class="muted">Reading the library…</p>`;
		let e = new Map(this.index.recipes.map((e) => [e.id, e])), t = /* @__PURE__ */ new Set(), n = this.index.families.map((n) => {
			let r = n.members.map((t) => e.get(t)).filter((e) => e !== void 0);
			for (let e of r) t.add(e.id);
			return {
				family: n,
				members: r
			};
		}), r = this.index.recipes.filter((e) => !t.has(e.id));
		return k`
      <h2>What are we cooking?</h2>
      ${n.map(({ family: e, members: t }) => k`
          <!-- A heading. Nothing resolves through a family, so nothing here is
               a button. -->
          <h3 class="family">${e.name}</h3>
          ${this.recipeList(t)}
        `)}
      ${r.length ? this.recipeList(r) : j}
      ${this.chosen ? this.batchesControl() : j}
    `;
	}
	recipeList(e) {
		return k`
      <ul class="recipes">
        ${e.map((e) => k`
            <li>
              <button
                type="button"
                aria-pressed=${this.chosen === e.id ? "true" : "false"}
                @click=${() => this.choose(e.id)}
              >
                ${e.name}
              </button>
            </li>
          `)}
      </ul>
    `;
	}
	batchesControl() {
		return k`
      <div class="batches">
        <h3>How many batches of ${this.index?.recipes.find((e) => e.id === this.chosen)?.name ?? ""}?</h3>
        <div class="row">
          <button
            type="button"
            aria-label="Fewer batches"
            ?disabled=${this.batches <= .5}
            @click=${() => this.step(-.5)}
          >
            −
          </button>
          <output>×${this.batches}</output>
          <button
            type="button"
            aria-label="More batches"
            ?disabled=${this.batches >= 20}
            @click=${() => this.step(.5)}
          >
            +
          </button>
        </div>
        <div class="movement">
          <span></span>
          <button type="button" class="primary" @click=${this.cook}>Start cooking</button>
        </div>
      </div>
    `;
	}
	choose(e) {
		this.chosen = this.chosen === e ? null : e;
	}
	step(e) {
		this.batches = Math.round(Math.min(20, Math.max(.5, this.batches + e)) * 2) / 2;
	}
	cook() {
		this.chosen && this.dispatchEvent(new CustomEvent("rw-cook", {
			detail: {
				recipeId: this.chosen,
				batches: this.batches
			},
			bubbles: !0,
			composed: !0
		}));
	}
};
H = Te, H.styles = [V], H.properties = {
	index: { attribute: !1 },
	chosen: { state: !0 },
	batches: { state: !0 }
}, customElements.define("recipe-wizard-picker", Te);
//#endregion
//#region src/countdown.ts
function Ee(e, t, n) {
	let r = t.estimateEndsAt;
	if (r === void 0) return {
		remainingMs: null,
		passed: !1,
		awaitingCheck: t.awaitingCheck
	};
	let i = r - n, a = i <= 0;
	return {
		remainingMs: i,
		passed: a,
		awaitingCheck: t.awaitingCheck || a && e.finishes_on === "state"
	};
}
function De(e) {
	let t = Math.max(0, Math.ceil(e / 1e3)), n = Math.floor(t / 3600), r = Math.floor(t % 3600 / 60), i = t % 60, a = (e) => String(e).padStart(2, "0");
	return n > 0 ? `${n}:${a(r)}:${a(i)}` : `${r}:${a(i)}`;
}
function Oe(e, t) {
	if (e <= 0) return null;
	let n = e % 1e3;
	return t + (n === 0 ? 1e3 : n);
}
//#endregion
//#region src/elements/step.ts
var U, ke = {
	active: "hands on",
	passive: "stay nearby",
	unattended: "you can walk away"
}, Ae = class extends B {
	constructor(...e) {
		super(...e), this.dish = null, this.step = null, this.countdown = {
			remainingMs: null,
			passed: !1,
			awaitingCheck: !1
		}, this.position = 0, this.of = 0, this.busy = !1;
	}
	render() {
		let e = this.step;
		return e ? k`
      <div class="row spread">
        <span class="position">${this.position}/${this.of}</span>
        <button type="button" @click=${() => this.emit("rw-stop")}>Stop</button>
      </div>
      <h2>${e.label}</h2>
      ${this.dish && this.dish.label !== e.label ? k`<p class="muted">for ${this.dish.label}</p>` : j}
      ${e.attention ? k`<span class="attention ${e.attention}"
            >${e.attention} · ${ke[e.attention]}</span
          >` : j}
      <p class="step-text">${e.text}</p>
      ${this.needs(e)} ${this.timing(e)}
      ${e.safety_note ? k`<p class="note">${e.safety_note}</p>` : j}
      <div class="movement">
        <button type="button" ?disabled=${this.busy} @click=${() => this.emit("rw-previous")}>
          Back
        </button>
        <button
          type="button"
          class="primary"
          ?disabled=${this.busy}
          @click=${() => this.emit("rw-next")}
        >
          ${this.countdown.awaitingCheck ? "It's ready — next" : "Next"}
        </button>
      </div>
    ` : k`<p class="muted">Nothing on the go.</p>`;
	}
	needs(e) {
		return e.needs.length ? k`
      <ul class="needs">
        ${e.needs.map((e) => k`
            <li>
              ${e.text}${e.optional ? k` <span class="muted">(optional)</span>` : j}
              ${e.required_state ? k`<span class="state">${e.required_state.description}</span>` : j}
              ${e.note ? k`<span class="state">${e.note}</span>` : j}
            </li>
          `)}
      </ul>
    ` : j;
	}
	timing(e) {
		let { remainingMs: t, passed: n, awaitingCheck: r } = this.countdown;
		return e.finishes_on === "state" ? k`
        <div class="timing ${r ? "awaiting" : ""}">
          <p class="doneness">
            <span class="lead">${r ? "Check now" : "Ends when"}</span>
            ${e.doneness ?? "the food says so"}
          </p>
          ${r ? k`<p class="stated">
                The estimate has run out. The step is over when it looks like that, not before.
              </p>` : t === null ? e.timer ? k`<p class="stated">estimated · ${e.timer}</p>` : j : k`
                  <p class="countdown estimate">${De(t)}</p>
                  <p class="stated">estimated · ${e.timer}</p>
                `}
          ${e.timer_starts_when ? k`<p class="stated">Timer starts when ${e.timer_starts_when}.</p>` : j}
        </div>
      ` : e.finishes_on === "clock" ? k`
        <div class="timing">
          ${t !== null && !n ? k`<p class="countdown">${De(t)}</p>` : t === null ? j : k`<p class="countdown">Time's up</p>`}
          ${e.timer ? k`<p class="stated">${e.timer}</p>` : j}
          ${e.timer_starts_when ? k`<p class="stated">Timer starts when ${e.timer_starts_when}.</p>` : j}
        </div>
      ` : k`<p class="stated">Done when you have done it.</p>`;
	}
	emit(e) {
		this.dispatchEvent(new CustomEvent(e, {
			bubbles: !0,
			composed: !0
		}));
	}
};
U = Ae, U.styles = [V], U.properties = {
	dish: { attribute: !1 },
	step: { attribute: !1 },
	countdown: { attribute: !1 },
	position: { type: Number },
	of: { type: Number },
	busy: { type: Boolean }
}, customElements.define("recipe-wizard-step", Ae);
//#endregion
//#region src/ports.ts
var je = {
	status: "idle",
	awaitingCheck: !1
}, W = class {
	now() {
		return Date.now();
	}
	schedule(e, t) {
		let n = Math.min(Math.max(e - this.now(), 0), 2 ** 31 - 1), r = setTimeout(t, n);
		return () => clearTimeout(r);
	}
}, Me = class {
	constructor(e = 0) {
		this.pending = [], this.time = e;
	}
	now() {
		return this.time;
	}
	schedule(e, t) {
		let n = {
			at: e,
			fn: t
		};
		return this.pending.push(n), e <= this.time && this.fire(), () => {
			this.pending = this.pending.filter((e) => e !== n);
		};
	}
	advance(e) {
		this.time += e, this.fire();
	}
	set(e) {
		if (e < this.time) throw Error("a clock does not run backwards");
		this.advance(e - this.time);
	}
	fire() {
		let e = this.pending.filter((e) => e.at <= this.time);
		this.pending = this.pending.filter((e) => e.at > this.time);
		for (let t of e) t.fn();
	}
}, G, K = class extends B {
	constructor(...e) {
		super(...e), this.source = null, this.clock = new W(), this.index = null, this.dish = null, this.cursor = je, this.busy = !1, this.error = null, this.tick = 0, this.unsubscribe = null, this.cancelTick = null, this.fetchedFor = null;
	}
	connectedCallback() {
		super.connectedCallback(), this.attach();
	}
	disconnectedCallback() {
		super.disconnectedCallback(), this.unsubscribe?.(), this.unsubscribe = null, this.cancelTick?.(), this.cancelTick = null;
	}
	willUpdate(e) {
		e.has("source") && this.attach();
	}
	attach() {
		this.unsubscribe?.(), this.unsubscribe = null;
		let e = this.source;
		!e || !this.isConnected || (this.unsubscribe = e.subscribe(() => this.sync()), e.library().then((e) => {
			this.index = e;
		}).catch((e) => this.blame(e)), this.sync());
	}
	sync() {
		let e = this.source;
		if (!e) return;
		this.cursor = e.cursor();
		let { status: t, recipeId: n, batches: r } = this.cursor;
		if (t === "idle" || n === void 0) {
			this.dish = null, this.fetchedFor = null;
			return;
		}
		let i = `${n}|${r ?? 1}`;
		(this.fetchedFor !== i || t === "cooking" && this.step() === null) && (this.fetchedFor = i, e.dish(n, r ?? 1).then((e) => {
			this.dish = e, this.error = null;
		}).catch((e) => {
			this.fetchedFor = null, this.blame(e);
		}));
	}
	step() {
		let e = this.dish, { stepId: t, stepRecipeId: n, position: r } = this.cursor;
		if (!e) return null;
		if (t !== void 0) {
			let r = e.steps.find((e) => e.step_id === t && (n === void 0 || e.recipe_id === n));
			if (r) return r;
			if (n !== void 0) return null;
		}
		return r !== void 0 && r >= 1 && r <= e.steps.length ? e.steps[r - 1] : null;
	}
	countdown(e) {
		return Ee(e, this.cursor, this.clock.now());
	}
	updated() {
		this.cancelTick?.(), this.cancelTick = null;
		let e = this.step();
		if (!e || this.cursor.status !== "cooking") return;
		let { remainingMs: t, passed: n } = this.countdown(e);
		if (t === null || n) return;
		let r = Oe(t, this.clock.now());
		r !== null && (this.cancelTick = this.clock.schedule(r, () => {
			this.tick += 1;
		}));
	}
	render() {
		return this.source ? k`
      ${this.error ? k`<p class="error">${this.error}</p>` : j} ${this.body()}
    ` : k`<p class="muted">No cook-along source.</p>`;
	}
	body() {
		switch (this.cursor.status) {
			case "idle": return k`
          <recipe-wizard-picker .index=${this.index} @rw-cook=${this.onCook}></recipe-wizard-picker>
        `;
			case "unknown": return k`
          <h2>Something is wrong with this recipe</h2>
          <p class="note">${this.cursor.problem ?? "The recipe will not resolve."}</p>
          <button type="button" @click=${this.onStop}>Stop</button>
        `;
			case "finished": return k`
          <h2>${this.dish?.label ?? "Done"}</h2>
          <p class="step-text">That's the last step. Enjoy it.</p>
          <div class="movement">
            <button type="button" @click=${this.onPrevious}>Back</button>
            <button type="button" class="primary" @click=${this.onStop}>Finish</button>
          </div>
        `;
			case "cooking": return this.cooking();
		}
	}
	cooking() {
		let e = this.step();
		return e ? k`
      <recipe-wizard-step
        .dish=${this.dish}
        .step=${e}
        .countdown=${this.countdown(e)}
        .position=${this.cursor.position ?? e.cursor + 1}
        .of=${this.cursor.of ?? e.of}
        ?busy=${this.busy}
        @rw-next=${this.onNext}
        @rw-previous=${this.onPrevious}
        @rw-stop=${this.onStop}
      ></recipe-wizard-step>
      ${this.findings()}
    ` : k`<p class="muted">Finding where you are…</p>`;
	}
	findings() {
		let e = this.dish?.findings ?? [];
		return e.length ? k`
      <ul class="findings">
        ${e.map((e) => k`<li>${e.message}</li>`)}
      </ul>
    ` : j;
	}
	onCook(e) {
		let { recipeId: t, batches: n } = e.detail;
		this.run(() => this.source.start(t, n));
	}
	onNext() {
		this.run(() => this.source.next());
	}
	onPrevious() {
		this.run(() => this.source.previous());
	}
	onStop() {
		this.run(() => this.source.stop());
	}
	async run(e) {
		if (!(this.busy || !this.source)) {
			this.busy = !0, this.error = null;
			try {
				await e(), this.sync();
			} catch (e) {
				this.blame(e);
			} finally {
				this.busy = !1;
			}
		}
	}
	blame(e) {
		this.error = e instanceof Error ? e.message : String(e);
	}
};
G = K, G.styles = [V], G.properties = {
	source: { attribute: !1 },
	clock: { attribute: !1 },
	index: { state: !0 },
	dish: { state: !0 },
	cursor: { state: !0 },
	busy: { state: !0 },
	error: { state: !0 },
	tick: { state: !0 }
}, customElements.define("recipe-wizard-surface", K);
var Ne = "recipe_wizard", q = class {
	constructor(e = {}) {
		this.listeners = /* @__PURE__ */ new Set(), this.hass = null, this.currentStepEntity = e.currentStepEntity ?? "sensor.recipe_wizard_current_step", this.stepTimerEntity = e.stepTimerEntity ?? "sensor.recipe_wizard_step_timer";
	}
	update(e) {
		this.hass = e;
		let t = e.states[this.currentStepEntity], n = e.states[this.stepTimerEntity], r = t !== this.lastCurrentStep || n !== this.lastStepTimer;
		this.lastCurrentStep = t, this.lastStepTimer = n, r && this.notify();
	}
	async library() {
		return await this.get("recipe_wizard/library");
	}
	async dish(e, t, n = !0) {
		let r = new URLSearchParams({
			batches: String(t),
			include_optional: String(n)
		});
		return this.get(`recipe_wizard/dish/${encodeURIComponent(e)}?${r}`);
	}
	cursor() {
		let e = this.hass?.states[this.currentStepEntity];
		if (!e || e.state === "unavailable") return {
			status: "idle",
			awaitingCheck: !1
		};
		let t = e.attributes, n = Y(t.batches, void 0), r = J(t.problem);
		if (r !== void 0 || e.state === "unknown" || e.state === "") return {
			status: "unknown",
			recipeId: this.dishId(t),
			batches: n,
			awaitingCheck: !1,
			problem: r ?? "The cook-along is not answering."
		};
		if (e.state === "idle") return {
			status: "idle",
			awaitingCheck: !1
		};
		if (e.state === "finished") return {
			status: "finished",
			recipeId: this.dishId(t),
			batches: n,
			of: Y(t.of, void 0),
			awaitingCheck: !1
		};
		let [i, a] = e.state.split("/").map((e) => Number(e)), o = this.estimateEndsAt();
		return {
			status: "cooking",
			recipeId: this.dishId(t),
			batches: n,
			stepId: J(t.step_id),
			stepRecipeId: J(t.recipe_id),
			position: Number.isFinite(i) ? i : Y(t.step_number, void 0),
			of: Number.isFinite(a) ? a : Y(t.of, void 0),
			...o === void 0 ? {} : { estimateEndsAt: o },
			awaitingCheck: t.awaiting_check === !0 || this.timerAttribute("awaiting_check") === !0
		};
	}
	subscribe(e) {
		return this.listeners.add(e), () => this.listeners.delete(e);
	}
	async start(e, t) {
		await this.call("start_cook_along", {
			recipe_id: e,
			batches: t
		});
	}
	async next() {
		await this.call("next_step");
	}
	async previous() {
		await this.call("previous_step");
	}
	async stop() {
		await this.call("stop_cook_along");
	}
	async call(e, t) {
		if (!this.hass) throw Error("Home Assistant is not connected yet.");
		await this.hass.callService(Ne, e, t);
	}
	async get(e) {
		let t = this.hass;
		if (!t) throw Error("Home Assistant is not connected yet.");
		if (t.callApi) return t.callApi("GET", e);
		let n = t.fetchWithAuth ? await t.fetchWithAuth(`/api/${e}`) : await fetch(`/api/${e}`);
		if (!n.ok) throw Error(`${n.status} from /api/${e}`);
		return await n.json();
	}
	estimateEndsAt() {
		let e = this.hass?.states[this.stepTimerEntity];
		if (!e) return;
		let t = Date.parse(e.state);
		return Number.isFinite(t) ? t : void 0;
	}
	timerAttribute(e) {
		return this.hass?.states[this.stepTimerEntity]?.attributes[e];
	}
	dishId(e) {
		return J(e.dish_id);
	}
	notify() {
		for (let e of [...this.listeners]) e();
	}
};
function J(e) {
	return typeof e == "string" && e !== "" ? e : void 0;
}
function Y(e, t) {
	return typeof e == "number" && Number.isFinite(e) ? e : t;
}
//#endregion
//#region src/panel.ts
var X, Z = class extends B {
	constructor(...e) {
		super(...e), this.source = new q(), this.clock = new W();
	}
	set hass(e) {
		this.source.update(e);
	}
	render() {
		return k`
      <div class="page">
        <recipe-wizard-surface
          .source=${this.source}
          .clock=${this.clock}
        ></recipe-wizard-surface>
      </div>
    `;
	}
};
X = Z, X.styles = o`
    :host {
      display: block;
      min-height: 100vh;
      background: var(--primary-background-color, #fafafa);
      padding: 16px;
      box-sizing: border-box;
    }

    .page {
      max-width: 720px;
      margin: 0 auto;
      padding: 24px;
      background: var(--card-background-color, #fff);
      border-radius: var(--ha-card-border-radius, 12px);
      box-shadow: var(--ha-card-box-shadow, 0 2px 4px rgba(0, 0, 0, 0.14));
      box-sizing: border-box;
    }
  `, customElements.define("recipe-wizard-panel", Z);
//#endregion
//#region src/card.ts
var Pe, Q = class extends B {
	constructor(...e) {
		super(...e), this.source = null, this.clock = new W(), this.hassObject = null;
	}
	static getStubConfig() {
		return { type: "custom:recipe-wizard-card" };
	}
	setConfig(e) {
		if (typeof e != "object" || !e) throw Error("A recipe-wizard card needs a configuration.");
		this.source = new q({
			currentStepEntity: e.current_step_entity ?? "sensor.recipe_wizard_current_step",
			stepTimerEntity: e.step_timer_entity ?? "sensor.recipe_wizard_step_timer"
		}), this.hassObject && this.source.update(this.hassObject), this.requestUpdate();
	}
	getCardSize() {
		return 10;
	}
	set hass(e) {
		this.hassObject = e, this.source?.update(e);
	}
	render() {
		return k`
      <ha-card>
        <recipe-wizard-surface
          .source=${this.source}
          .clock=${this.clock}
        ></recipe-wizard-surface>
      </ha-card>
    `;
	}
};
Pe = Q, Pe.styles = o`
    ha-card {
      padding: 20px;
    }
  `, customElements.define("recipe-wizard-card", Q);
//#endregion
//#region src/fixture-source.ts
var Fe = class {
	constructor(e, t, n = new W()) {
		this.index = e, this.dishes = t, this.clock = n, this.listeners = /* @__PURE__ */ new Set(), this.saved = null, this.finished = !1, this.awaiting = !1, this.cancelWake = null;
	}
	async library() {
		return this.index;
	}
	async dish(e, t) {
		let n = this.dishes[e];
		if (!n) throw Error(`no fixture for ${e}`);
		return {
			...n,
			batches: t
		};
	}
	cursor() {
		if (!this.saved) return {
			status: "idle",
			awaitingCheck: !1
		};
		let e = this.dishes[this.saved.dishId];
		if (!e) return {
			status: "unknown",
			recipeId: this.saved.dishId,
			batches: this.saved.batches,
			awaitingCheck: !1,
			problem: `no fixture for ${this.saved.dishId}`
		};
		let t = this.locate(e);
		if (this.finished || t < 0) return {
			status: "finished",
			recipeId: this.saved.dishId,
			batches: this.saved.batches,
			of: e.steps.length,
			awaitingCheck: !1
		};
		let n = e.steps[t], r = this.estimateEndsAt();
		return {
			status: "cooking",
			recipeId: this.saved.dishId,
			batches: this.saved.batches,
			stepId: n.step_id,
			stepRecipeId: n.recipe_id,
			position: t + 1,
			of: e.steps.length,
			...r === null ? {} : { estimateEndsAt: r },
			awaitingCheck: this.awaiting
		};
	}
	subscribe(e) {
		return this.listeners.add(e), () => this.listeners.delete(e);
	}
	async start(e, t) {
		if (!this.index.recipes.some((t) => t.id === e)) throw Error(`not a recipe: ${e}`);
		let n = this.dishes[e];
		if (!n || n.steps.length === 0) throw Error(`nothing to cook in ${e}`);
		this.finished = !1, this.arrive(e, t, n.steps[0]);
	}
	async next() {
		this.move(1);
	}
	async previous() {
		this.move(-1);
	}
	async stop() {
		this.saved = null, this.finished = !1, this.disarm(), this.notify();
	}
	locate(e) {
		let t = this.saved;
		return t ? e.steps.findIndex((e) => e.step_id === t.stepId && e.recipe_id === t.stepRecipeId) : -1;
	}
	move(e) {
		if (!this.saved || this.finished) return;
		let t = this.dishes[this.saved.dishId];
		if (!t) return;
		let n = this.locate(t);
		if (n < 0) return;
		let r = n + e;
		if (!(r < 0)) {
			if (r >= t.steps.length) {
				this.finished = !0, this.disarm(), this.notify();
				return;
			}
			this.arrive(this.saved.dishId, this.saved.batches, t.steps[r]);
		}
	}
	arrive(e, t, n) {
		this.saved = {
			dishId: e,
			batches: t,
			stepRecipeId: n.recipe_id,
			stepId: n.step_id,
			startedAt: this.clock.now()
		}, this.awaiting = !1, this.disarm();
		let r = this.estimateEndsAt();
		r !== null && n.finishes_on === "state" && (this.cancelWake = this.clock.schedule(r, () => {
			this.awaiting = !0, this.notify();
		})), this.notify();
	}
	currentStep() {
		if (!this.saved) return;
		let e = this.dishes[this.saved.dishId];
		if (!e) return;
		let t = this.locate(e);
		return t < 0 ? void 0 : e.steps[t];
	}
	estimateEndsAt() {
		let e = this.currentStep();
		return !this.saved || !e || e.timer_s === void 0 || e.timer_starts_when !== void 0 ? null : this.saved.startedAt + e.timer_s * 1e3;
	}
	disarm() {
		this.cancelWake?.(), this.cancelWake = null;
	}
	notify() {
		for (let e of [...this.listeners]) e();
	}
}, $ = window.customCards ??= [];
$.some((e) => e.type === "recipe-wizard-card") || $.push({
	type: "recipe-wizard-card",
	name: "Recipe Wizard cook-along",
	description: "Cook along with a recipe: one step at a time, at your batch size."
});
//#endregion
export { Fe as FixtureCookAlongSource, q as HassCookAlongSource, Me as ManualClock, Q as RecipeWizardCard, Z as RecipeWizardPanel, K as RecipeWizardSurface, W as SystemClock };
