from flask import Blueprint, jsonify, request, session, redirect, url_for, flash, render_template
from flask_login import login_required, current_user
from app.services.translation_service import TranslationService
from app.extensions import db

SUPPORTED = {'en', 'ne', 'newari', 'maithili'}

language_bp = Blueprint('language', __name__)
translation_service = TranslationService()

@language_bp.route('/set/<lang>')
def set_language(lang):
    """Set user language preference."""
    if lang not in SUPPORTED:
        flash('Unsupported language', 'error')
        return redirect(request.referrer or url_for('main.index'))

    session['language'] = lang
    
    if current_user.is_authenticated:
        current_user.language = lang
        db.session.commit()
    
    return redirect(request.referrer or url_for('main.index'))

@language_bp.route('/get/<key>')
def get_translation(key):
    """Get translation for a key."""
    lang = session.get('language', 'ne')
    translation = translation_service.get_translation(lang, key)
    return jsonify({'translation': translation})

@language_bp.route('/languages')
def get_languages():
    """Get supported languages."""
    return jsonify(translation_service.get_supported_languages())

@language_bp.route('/translate', methods=['POST'])
@login_required
def translate():
    """Translate text using AI."""
    text = request.json.get('text', '')
    target_lang = request.json.get('target_lang', 'ne')
    
    if not text:
        return jsonify({'error': 'Text required'}), 400
    
    translated = translation_service.translate_text(text, target_lang)
    return jsonify({'translated': translated})