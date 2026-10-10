// A stand-in for Supabase, for the second desk (prototype/desk.template.html) run online in a headless browser.
// The test fills window.__FAKE__ before this script: the deck, everyone's reviews and holds, and the search file.
(function () {
  const F = window.__FAKE__;
  F.rpcs = []; F.upserts = []; F.refuse = new Set(); F.conflict = new Set(); F.fail = false;
  let user = null;
  const rows = table => table === "deck" ? F.deck : table === "reviews" ? F.reviews : table === "claims" ? F.claims : [];
  const client = {
    auth: {
      getSession: async () => ({ data: { session: user ? { user } : null } }),
      signInWithPassword: async ({ email, password }) => {
        if (password !== "pw") return { data: null, error: { message: "bad" } };
        user = email.startsWith("test")
          ? { id: "u9", email, user_metadata: { name: "Tester" }, app_metadata: { test: true } }
          : { id: "u1", email, user_metadata: { name: "Glenn" }, app_metadata: {} };
        return { data: { user }, error: null };
      },
      signOut: async () => { user = null; return {}; },
    },
    from(table) {
      return {
        select: () => ({ order: () => ({ range: async (a, b) => ({ data: rows(table).slice(a, b + 1), error: null }) }) }),
        upsert: async (list) => {
          if (F.fail) throw new Error("offline");
          if (list.some(r => F.conflict.has(r.card_key))) return { data: null, error: { code: "23505" } };
          F.upserts.push(...list);
          return { data: list, error: null };
        },
      };
    },
    rpc: async (name, args) => {
      F.rpcs.push(name + ":" + args.key);
      if (name === "claim_card") return { data: !F.refuse.has(args.key), error: null };
      return { data: true, error: null };
    },
    storage: { from: () => ({ download: async () => ({ data: { text: async () => JSON.stringify(F.desk) } }) }) },
  };
  window.supabase = { createClient: () => client };
})();
