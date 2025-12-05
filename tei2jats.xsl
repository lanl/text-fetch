<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:tei="http://www.tei-c.org/ns/1.0"
    xmlns:j="http://jats.nlm.nih.gov"
    exclude-result-prefixes="tei"
    version="2.0">

    <!-- Strip random whitespace in source -->
    <xsl:strip-space elements="*"/>

    <!-- Nice formatting in output; you can turn this off in production -->
    <xsl:output method="xml"
                indent="yes"
                encoding="UTF-8"/>

    <!-- ==================================================================
         3.1 Root: TEI → j:article
         ================================================================== -->

    <xsl:template match="/tei:TEI">
        <j:article article-type="research-article">
            <xsl:call-template name="build-front"/>
            <xsl:call-template name="build-body"/>
            <xsl:call-template name="build-back"/>
        </j:article>
    </xsl:template>

    <!-- ==================================================================
         3.2 Front matter (title, authors, basic metadata)
         ================================================================== -->

    <xsl:template name="build-front">
        <j:front>
            <j:article-meta>
                <!-- Article title: take first title in titleStmt -->
                <xsl:variable name="title"
                              select="tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title[1]"/>
                <xsl:if test="$title">
                    <j:title-group>
                        <j:article-title>
                            <xsl:value-of select="normalize-space($title)"/>
                        </j:article-title>
                    </j:title-group>
                </xsl:if>

                <!-- Authors: very basic mapping from tei:author/tei:persName -->
                <xsl:variable name="authors"
                              select="tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author"/>
                <xsl:if test="$authors">
                    <j:contrib-group>
                        <xsl:for-each select="$authors">
                            <j:contrib contrib-type="author">
                                <j:name>
                                    <!-- You can refine this based on how GROBID emits names -->
                                    <xsl:variable name="pers"
                                                  select=".//tei:persName[1]"/>
                                    <xsl:variable name="surname"
                                                  select="$pers/tei:surname"/>
                                    <xsl:variable name="forename"
                                                  select="$pers/tei:forename[1]"/>

                                    <xsl:if test="$surname">
                                        <j:surname>
                                            <xsl:value-of select="normalize-space($surname)"/>
                                        </j:surname>
                                    </xsl:if>

                                    <xsl:if test="$forename">
                                        <j:given-names>
                                            <xsl:value-of select="normalize-space($forename)"/>
                                        </j:given-names>
                                    </xsl:if>
                                </j:name>
                            </j:contrib>
                        </xsl:for-each>
                    </j:contrib-group>
                </xsl:if>

                <!-- Extract abstract -->
                <xsl:variable name="abstract" select="tei:teiHeader/tei:profileDesc/tei:abstract"/>
                <xsl:if test="$abstract">
                    <j:abstract>
                        <xsl:apply-templates select="$abstract/node()"/>
                    </j:abstract>
                </xsl:if>

                <!-- TODO: add publication date, journal meta, etc., later -->
            </j:article-meta>
        </j:front>
    </xsl:template>

    <!-- ==================================================================
         3.3 Body: basic section/paragraph mapping
         ================================================================== -->

    <xsl:template name="build-body">
        <!-- GROBID TEI typically has: /TEI/text/body -->
        <xsl:variable name="body" select="tei:text/tei:body"/>
        <xsl:if test="$body">
            <j:body>
                <xsl:apply-templates select="$body/node()"/>
            </j:body>
        </xsl:if>
    </xsl:template>

    <!-- Map TEI div → JATS sec -->
    <xsl:template match="tei:div">
        <j:sec>
            <!-- Optional: use @type or @n to annotate sec-type or label -->
            <xsl:if test="@type">
                <xsl:attribute name="sec-type">
                    <xsl:value-of select="@type"/>
                </xsl:attribute>
            </xsl:if>

            <!-- Section title -->
            <xsl:if test="tei:head">
                <j:title>
                    <xsl:value-of select="normalize-space(tei:head[1])"/>
                </j:title>
            </xsl:if>

            <!-- Section content -->
            <xsl:apply-templates select="node()[not(self::tei:head)]"/>
        </j:sec>
    </xsl:template>

    <!-- Paragraphs -->
    <xsl:template match="tei:p">
        <j:p>
            <xsl:apply-templates/>
        </j:p>
    </xsl:template>

    <!-- Headings inside body (if any) -->
    <xsl:template match="tei:head">
        <j:title>
            <xsl:apply-templates/>
        </j:title>
    </xsl:template>

    <!-- ==================================================================
         3.4 Back matter: placeholder
         ================================================================== -->

    <xsl:template name="build-back">
        <!-- For now, do nothing.
             Later you can map tei:back, tei:listBibl → j:back/j:ref-list. -->
    </xsl:template>

    <!-- ==================================================================
         3.5 Inline formatting (minimal)
         ================================================================== -->

    <!-- Emphasis (e.g., <hi rend="italic">) -->
    <xsl:template match="tei:hi[@rend='italic' or @rend='italics' or @rend='emph' or @rendition='#i']">
        <j:italic>
            <xsl:apply-templates/>
        </j:italic>
    </xsl:template>

    <!-- Bold -->
    <xsl:template match="tei:hi[@rend='bold' or @rendition='#b']">
        <j:bold>
            <xsl:apply-templates/>
        </j:bold>
    </xsl:template>

    <!-- Line breaks -->
    <xsl:template match="tei:lb">
        <j:break/>
    </xsl:template>

    <!-- ==================================================================
         3.6 Generic fallbacks
         ================================================================== -->

    <!-- Default: for text nodes, just copy the text -->
    <xsl:template match="text()">
        <xsl:value-of select="."/>
    </xsl:template>

    <!-- Fallback for any TEI element without an explicit rule:
         flatten it to its children (ignore the element wrapper). -->
    <xsl:template match="tei:*">
        <xsl:apply-templates/>
    </xsl:template>

    <!-- Ignore comments and processing instructions -->
    <xsl:template match="comment() | processing-instruction()"/>

</xsl:stylesheet>
