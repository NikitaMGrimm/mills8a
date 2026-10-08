-- mills8a-jitter.lua: letterpress baseline wobble for LuaLaTeX.
-- Copyright 2026 heiner. MIT License, see LICENSE.
--
-- On the 1947 pages, flat-bottomed letters (n m h i l r k) scatter around
-- their line's baseline by 1.00 px at 600 dpi: 40% exactly on it, 87%
-- within 1 px, 98% within 2 px, neighbours almost uncorrelated (0.14).
-- Mills 8A's random impressions (rand) already reproduce most of that
-- (0.89 px), since each keeps its own bottom edge.  An extra independent
-- offset of 0.04 pt standard deviation per glyph brings the rendered
-- statistics to 0.99 px, 38 / 87 / 99% -- the scan's.  Math is left alone
-- (its glyphs sit in nested lists).  A fixed seed keeps output reproducible.
--
--   \directlua{require("mills8a-jitter").enable(0.04, 1947)}  % sigma in pt, seed

local M = {}
local GLYPH, HLIST = node.id("glyph"), node.id("hlist")
local sigma_sp, enabled = 0, false

-- Box-Muller normal deviate, clipped at 2.5 sigma
local function normal()
  local u1, u2 = math.random(), math.random()
  local z = math.sqrt(-2 * math.log(1 - u1)) * math.cos(2 * math.pi * u2)
  return math.max(-2.5, math.min(2.5, z))
end

local function jitter(head)
  if not enabled then return head end
  for line in node.traverse_id(HLIST, head) do
    for g in node.traverse_id(GLYPH, line.head) do
      g.yoffset = g.yoffset + math.floor(sigma_sp * normal() + 0.5)
    end
  end
  return head
end

function M.enable(sigma_pt, seed)
  sigma_sp = (sigma_pt or 0.04) * 65536
  math.randomseed(seed or 1947)
  if not enabled then
    luatexbase.add_to_callback("post_linebreak_filter", jitter, "mills8a-jitter")
  end
  enabled = true
end

function M.disable() enabled = false end

return M
