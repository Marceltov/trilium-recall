from text import approx_tokens, content_hash, html_to_sections


def test_splits_at_h2_and_h3():
    s = html_to_sections("<p>intro</p><h2>A</h2><p>a</p><h3>B</h3><p>b</p><h2>C</h2><p>c</p>")
    assert [(x.heading_path, x.text) for x in s] == [
        ((), "intro"), (("A",), "a"), (("A", "B"), "b"), (("C",), "c")]
    assert [x.ordinal for x in s] == [0, 1, 2, 3]


def test_lists_tables_pre():
    s = html_to_sections("<ul><li>x</li><li>y</li></ul><table><tr><td>1</td><td>2</td></tr></table><pre>a  b\n c</pre>")
    assert s[0].text == "- x\n- y\n1 | 2\na  b\n c"


def test_drops_mermaid():
    assert html_to_sections('<p>k</p><pre><code class="language-mermaid">flowchart LR</code></pre>')[0].text == "k"


def test_long_section_split_keeps_heading():
    html = "<h2>H</h2>" + "".join(f"<p>{'w ' * 100}</p>" for _ in range(10))
    parts = html_to_sections(html, max_tokens=350)
    assert len(parts) >= 3 and all(p.heading_path == ("H",) for p in parts)
    assert all(approx_tokens(p.text) <= 350 for p in parts)


def test_empty_and_german():
    assert html_to_sections("") == []
    assert "Übergröße & Maß" in html_to_sections("<p>Übergröße &amp; Maß</p>")[0].text


def test_inline_markup_and_h4_stay_text():
    s = html_to_sections("<h2>A</h2><p>a <strong>bold</strong> <a href='#'>link</a></p><h4>Sub</h4><p>z</p>")
    assert s == [s[0]] and s[0].text == "a bold link\nSub\nz"


def test_plain_text_input():
    s = html_to_sections("line one\nline two", plain=True)
    assert s[0].heading_path == () and s[0].text == "line one\nline two"


def test_content_hash_stable():
    assert content_hash("x") == content_hash("x") != content_hash("y")


def test_br_and_nested_blocks_keep_words_apart():
    assert html_to_sections("<p>foo<br>bar</p>")[0].text == "foo bar"
    assert html_to_sections("<ul><li><p>x</p><p>y</p></li></ul>")[0].text == "- x y"
    assert html_to_sections("<table><tr><td><p>a</p><p>b</p></td></tr></table>")[0].text == "a b"
