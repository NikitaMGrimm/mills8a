-- mills8a-jitter.lua: letterpress baseline wobble for LuaLaTeX.
--
-- On the 1947 pages, impressions of the same letter scatter around their
-- line's baseline by about 1 px at 600 dpi (0.12 pt standard deviation;
-- roughly 0.08 pt once measurement noise is allowed for).  This gives every
-- glyph in a typeset line a random vertical offset with that spread.
-- Math is left alone (its glyphs sit in nested lists).  A fixed seed keeps
-- the output reproducible.
--
--   \directlua{require("mills8a-jitter").enable(0.08, 1947)}  % sigma in pt, seed

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
  sigma_sp = (sigma_pt or 0.08) * 65536
  math.randomseed(seed or 1947)
  if not enabled then
    luatexbase.add_to_callback("post_linebreak_filter", jitter, "mills8a-jitter")
  end
  enabled = true
end

function M.disable() enabled = false end

return M
