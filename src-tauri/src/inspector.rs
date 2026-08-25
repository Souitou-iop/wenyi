use std::fs::File;
use std::io::Read;
use std::path::Path;
use crate::types::BookMetadata;

pub struct BookInspector;

impl BookInspector {
    pub fn inspect_file(path_str: &str, cache_dir: Option<&Path>) -> Result<BookMetadata, String> {
        let path = Path::new(path_str);
        if !path.exists() {
            return Err("文件不存在".to_string());
        }

        let metadata = std::fs::metadata(path).map_err(|e| format!("读取文件属性失败: {}", e))?;
        let file_size = metadata.len();
        let filename = path.file_name().unwrap_or_default().to_string_lossy().to_string();
        let extension = path.extension().unwrap_or_default().to_string_lossy().to_lowercase();
        let book_id = uuid::Uuid::new_v4().to_string();

        match extension.as_str() {
            "epub" => Self::inspect_epub(path, &filename, file_size, &book_id, cache_dir),
            "docx" => Self::inspect_docx(path, &filename, file_size, &book_id, cache_dir),
            "srt" => Self::inspect_srt(path, &filename, file_size, &book_id),
            "txt" | "md" | "markdown" => Self::inspect_text(path, &filename, file_size, &book_id, &extension),
            _ => Ok(Self::empty_metadata(path, &filename, file_size, &book_id, &extension)),
        }
    }

    fn empty_metadata(path: &Path, filename: &str, file_size: u64, book_id: &str, format: &str) -> BookMetadata {
        let stem = path.file_stem().unwrap_or_default().to_string_lossy().to_string();
        BookMetadata {
            id: book_id.to_string(),
            path: path.to_string_lossy().to_string(),
            filename: filename.to_string(),
            format: format.to_string(),
            title: stem,
            authors: vec![],
            language: "auto".to_string(),
            description: String::new(),
            chapter_count: 1,
            file_size,
            cover_path: None,
        }
    }

    fn inspect_epub(
        path: &Path,
        filename: &str,
        file_size: u64,
        book_id: &str,
        cache_dir: Option<&Path>,
    ) -> Result<BookMetadata, String> {
        let file = File::open(path).map_err(|e| format!("打开 EPUB 失败: {}", e))?;
        let mut archive = zip::ZipArchive::new(file).map_err(|e| format!("解压 EPUB 失败: {}", e))?;

        let mut opf_path_str = String::new();
        if let Ok(mut container) = archive.by_name("META-INF/container.xml") {
            let mut xml = String::new();
            let _ = container.read_to_string(&mut xml);
            if let Some(start) = xml.find("full-path=\"") {
                let rest = &xml[start + 11..];
                if let Some(end) = rest.find('"') {
                    opf_path_str = rest[..end].to_string();
                }
            }
        }

        let mut opf_content = String::new();
        let mut found_opf = false;

        if !opf_path_str.is_empty() {
            if let Ok(mut opf_file) = archive.by_name(&opf_path_str) {
                let _ = opf_file.read_to_string(&mut opf_content);
                found_opf = true;
            }
        }

        if !found_opf {
            let total_files = archive.len();
            for i in 0..total_files {
                let is_opf = if let Ok(f) = archive.by_index(i) {
                    f.name().ends_with(".opf")
                } else {
                    false
                };

                if is_opf {
                    if let Ok(mut f) = archive.by_index(i) {
                        let _ = f.read_to_string(&mut opf_content);
                        opf_path_str = f.name().to_string();
                        found_opf = true;
                        break;
                    }
                }
            }
        }

        if !found_opf {
            return Ok(Self::empty_metadata(path, filename, file_size, book_id, "epub"));
        }

        let title = extract_xml_tag(&opf_content, "dc:title")
            .unwrap_or_else(|| path.file_stem().unwrap_or_default().to_string_lossy().to_string());
        let creator = extract_xml_tag(&opf_content, "dc:creator");
        let language = extract_xml_tag(&opf_content, "dc:language").unwrap_or_else(|| "zh".to_string());
        let description = extract_xml_tag(&opf_content, "dc:description").unwrap_or_default();

        // 估算章节数：统计 itemref 数量
        let chapter_count = opf_content.matches("<itemref ").count().max(1);

        // 尝试提取封面
        let mut cover_path = None;
        if let Some(cache) = cache_dir {
            if let Some(cover_href) = find_epub_cover_href(&opf_content, &opf_path_str) {
                if let Ok(mut cover_file) = archive.by_name(&cover_href) {
                    let ext = Path::new(&cover_href).extension().unwrap_or_default().to_string_lossy();
                    let target_name = format!("{}.{}", book_id, if ext.is_empty() { "jpg" } else { &ext });
                    let target_path = cache.join(target_name);
                    let _ = std::fs::create_dir_all(cache);
                    let mut buffer = Vec::new();
                    if cover_file.read_to_end(&mut buffer).is_ok() {
                        if std::fs::write(&target_path, buffer).is_ok() {
                            cover_path = Some(target_path.to_string_lossy().to_string());
                        }
                    }
                }
            }
        }

        Ok(BookMetadata {
            id: book_id.to_string(),
            path: path.to_string_lossy().to_string(),
            filename: filename.to_string(),
            format: "epub".to_string(),
            title,
            authors: creator.into_iter().collect(),
            language,
            description,
            chapter_count,
            file_size,
            cover_path,
        })
    }

    fn inspect_docx(
        path: &Path,
        filename: &str,
        file_size: u64,
        book_id: &str,
        _cache_dir: Option<&Path>,
    ) -> Result<BookMetadata, String> {
        let file = File::open(path).map_err(|e| format!("打开 DOCX 失败: {}", e))?;
        let mut archive = zip::ZipArchive::new(file).map_err(|e| format!("解压 DOCX 失败: {}", e))?;

        let mut title = path.file_stem().unwrap_or_default().to_string_lossy().to_string();
        let mut authors = Vec::new();
        let mut description = String::new();

        if let Ok(mut core_file) = archive.by_name("docProps/core.xml") {
            let mut core_xml = String::new();
            let _ = core_file.read_to_string(&mut core_xml);
            if let Some(t) = extract_xml_tag(&core_xml, "dc:title") {
                if !t.trim().is_empty() {
                    title = t;
                }
            }
            if let Some(c) = extract_xml_tag(&core_xml, "dc:creator") {
                authors.push(c);
            }
            if let Some(d) = extract_xml_tag(&core_xml, "dc:description") {
                description = d;
            }
        }

        let mut chapter_count = 1;
        if let Ok(mut doc_file) = archive.by_name("word/document.xml") {
            let mut doc_xml = String::new();
            let _ = doc_file.read_to_string(&mut doc_xml);
            let heading_count = doc_xml.matches("val=\"Heading").count() + doc_xml.matches("val=\"heading").count();
            if heading_count > 0 {
                chapter_count = heading_count;
            }
        }

        Ok(BookMetadata {
            id: book_id.to_string(),
            path: path.to_string_lossy().to_string(),
            filename: filename.to_string(),
            format: "docx".to_string(),
            title,
            authors,
            language: "zh".to_string(),
            description,
            chapter_count,
            file_size,
            cover_path: None,
        })
    }

    fn inspect_srt(path: &Path, filename: &str, file_size: u64, book_id: &str) -> Result<BookMetadata, String> {
        let content = std::fs::read_to_string(path).unwrap_or_default();
        let cue_count = content.matches("-->").count().max(1);
        let title = path.file_stem().unwrap_or_default().to_string_lossy().to_string();

        Ok(BookMetadata {
            id: book_id.to_string(),
            path: path.to_string_lossy().to_string(),
            filename: filename.to_string(),
            format: "srt".to_string(),
            title,
            authors: vec![],
            language: "auto".to_string(),
            description: format!("包含 {} 条字幕轨段", cue_count),
            chapter_count: cue_count,
            file_size,
            cover_path: None,
        })
    }

    fn inspect_text(
        path: &Path,
        filename: &str,
        file_size: u64,
        book_id: &str,
        format: &str,
    ) -> Result<BookMetadata, String> {
        let content = std::fs::read_to_string(path).unwrap_or_default();
        let line_count = content.lines().count();
        let title = path.file_stem().unwrap_or_default().to_string_lossy().to_string();

        let chapter_matches = content
            .lines()
            .filter(|l| {
                let trimmed = l.trim();
                trimmed.starts_with("# ") || trimmed.starts_with("## ") || (trimmed.starts_with("第") && trimmed.contains("章"))
            })
            .count();

        Ok(BookMetadata {
            id: book_id.to_string(),
            path: path.to_string_lossy().to_string(),
            filename: filename.to_string(),
            format: format.to_string(),
            title,
            authors: vec![],
            language: "auto".to_string(),
            description: format!("文本共 {} 行", line_count),
            chapter_count: chapter_matches.max(1),
            file_size,
            cover_path: None,
        })
    }
}

fn extract_xml_tag(xml: &str, tag: &str) -> Option<String> {
    let open_tag = format!("<{}", tag);
    let close_tag = format!("</{}", tag);

    if let Some(start_pos) = xml.find(&open_tag) {
        let after_open = &xml[start_pos..];
        if let Some(gt_pos) = after_open.find('>') {
            let content_start = &after_open[gt_pos + 1..];
            if let Some(end_pos) = content_start.find(&close_tag) {
                let text = &content_start[..end_pos];
                return Some(text.trim().to_string());
            }
        }
    }
    None
}

fn find_epub_cover_href(opf: &str, opf_path: &str) -> Option<String> {
    let opf_dir = Path::new(opf_path).parent().unwrap_or_else(|| Path::new(""));

    // 1. properties="cover-image"
    if let Some(pos) = opf.find("properties=\"cover-image\"") {
        let segment = &opf[..pos];
        if let Some(href_start) = segment.rfind("href=\"") {
            let rest = &segment[href_start + 6..];
            if let Some(end) = rest.find('"') {
                let rel = &rest[..end];
                return Some(opf_dir.join(rel).to_string_lossy().to_string());
            }
        }
    }

    // 2. id="cover" or id="cover-image"
    for id_pattern in ["id=\"cover\"", "id=\"cover-image\"", "id=\"cover_image\""] {
        if let Some(pos) = opf.find(id_pattern) {
            let segment = &opf[pos..pos.saturating_add(200).min(opf.len())];
            if let Some(href_start) = segment.find("href=\"") {
                let rest = &segment[href_start + 6..];
                if let Some(end) = rest.find('"') {
                    let rel = &rest[..end];
                    return Some(opf_dir.join(rel).to_string_lossy().to_string());
                }
            }
        }
    }

    None
}
